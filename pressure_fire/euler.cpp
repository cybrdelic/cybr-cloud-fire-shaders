// Conservative, reactive, compressible Euler reference solver.
// Build: g++ -O3 -std=c++17 -fopenmp euler.cpp -o euler
// Binary input/output: little-endian float32 [nz,ny,nx,8], x fastest.
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <string>
#include <vector>
#include <omp.h>

using Cell = std::array<float,8>;
using Totals = std::array<double,8>;
struct Config {
    int nx=48, ny=56, nz=48, threads=8;
    double dx=.25,dy=.25,dz=.25, gamma=1.3,cfl=.35;
    double t_end=.5, output_dt=.125, gravity=.10, cooling=4.0;
    double rate=2.0, heat=65., oxygen_ratio=3., soot_yield=.16;
    double ignition=1.3, active=2.0, pressure_ambient=1., rho_ambient=1.;
    double initial_time=0., max_dt=1e100, confinement=0.;
    bool pressure=true, source=true, first_order=false;
    std::string input, output;
} cfg;

static inline double minmod(double a,double b,double c) {
    if (a>0 && b>0 && c>0) return std::min(a,std::min(b,c));
    if (a<0 && b<0 && c<0) return std::max(a,std::max(b,c));
    return 0.;
}
static inline double slope(double a,double b,double c) {
    return minmod(1.5*(b-a),.5*(c-a),1.5*(c-b));
}

struct Solver {
    int nx,ny,nz,gx,gy,gz; size_t n,ng;
    std::vector<Cell> u,a,b,rhs,q,faces;
    std::vector<std::array<float,4>> curl;
    Totals flow_source{};
    Totals initial{},boundary{},sources{},tiny_correction{};
    double t=0., max_cfl=0., elapsed=0.;
    int steps=0,rejects=0;
    Solver():nx(cfg.nx),ny(cfg.ny),nz(cfg.nz),gx(nx+4),gy(ny+4),gz(nz+4),
      n(size_t(nx)*ny*nz),ng(size_t(gx)*gy*gz),u(n),a(n),b(n),rhs(n),q(ng),
      faces(std::max({size_t(nx+1)*ny*nz,size_t(nx)*(ny+1)*nz,size_t(nx)*ny*(nz+1)})),curl(ng) {}
    inline size_t id(int x,int y,int z) const {return (size_t(z)*ny+y)*nx+x;}
    inline size_t qi(int x,int y,int z) const {return (size_t(z)*gy+y)*gx+x;}
    inline size_t fi(int x,int y,int z,int ax) const {
        int fx=nx+(ax==0), fy=ny+(ax==1);
        return (size_t(z)*fy+y)*fx+x;
    }
    Totals sum(const std::vector<Cell>& v) {
        Totals out{}; double dv=cfg.dx*cfg.dy*cfg.dz;
        for (const auto& c:v) for(int k=0;k<8;k++) out[k]+=double(c[k])*dv;
        return out;
    }
    void load() {
        std::ifstream f(cfg.input,std::ios::binary);
        if(!f) throw std::runtime_error("Cannot open input "+cfg.input);
        f.read(reinterpret_cast<char*>(u.data()),n*sizeof(Cell));
        if(size_t(f.gcount())!=n*sizeof(Cell)) throw std::runtime_error("Input size mismatch");
        initial=sum(u); t=cfg.initial_time;
    }
    void primitives(const std::vector<Cell>& v) {
        #pragma omp parallel for collapse(2) schedule(static)
        for(int z=0;z<gz;z++) for(int y=0;y<gy;y++) for(int x=0;x<gx;x++) {
            const Cell& s=v[id(std::clamp(x-2,0,nx-1),std::clamp(y-2,0,ny-1),std::clamp(z-2,0,nz-1))];
            Cell p{}; double rho=s[0], inv=1/rho;
            p[0]=rho;
            double ke=0;
            for(int k=1;k<4;k++){p[k]=s[k]*inv;ke+=double(s[k])*s[k]*.5*inv;}
            p[4]=(cfg.gamma-1)*(s[4]-ke);
            for(int k=5;k<8;k++)p[k]=s[k]*inv;
            q[qi(x,y,z)]=p;
        }
    }
    void conserved(const Cell& qv, std::array<double,8>& s) const {
        double rho=qv[0];s[0]=rho;
        double ke=0;for(int k=1;k<4;k++){s[k]=rho*qv[k];ke+=.5*rho*qv[k]*qv[k];}
        s[4]=qv[4]/(cfg.gamma-1)+ke;
        for(int k=5;k<8;k++)s[k]=rho*qv[k];
    }
    Cell riemann(const Cell& l,const Cell& r,int ax) const {
        std::array<double,8> ul{},ur{},fl{},fr{},out{};
        conserved(l,ul);conserved(r,ur);
        int normal=ax+1;double vl=l[normal],vr=r[normal];
        double pl=cfg.pressure?l[4]:cfg.pressure_ambient;
        double pr=cfg.pressure?r[4]:cfg.pressure_ambient;
        double cl=std::sqrt(cfg.gamma*pl/l[0]),cr=std::sqrt(cfg.gamma*pr/r[0]);
        double sl=std::min(vl-cl,vr-cr),sr=std::max(vl+cl,vr+cr);
        for(int k=0;k<8;k++){fl[k]=ul[k]*vl;fr[k]=ur[k]*vr;}
        fl[normal]+=pl;fr[normal]+=pr;fl[4]+=pl*vl;fr[4]+=pr*vr;
        if(sl>=0)out=fl;
        else if(sr<=0)out=fr;
        else {
            double al=l[0]*(sl-vl),ar=r[0]*(sr-vr);
            double sm=(pr-pl+al*vl-ar*vr)/(al-ar);
            bool left=sm>=0;
            const auto& s=left?ul:ur;const auto& f=left?fl:fr;
            const Cell& qq=left?l:r;
            double sk=left?sl:sr,vk=left?vl:vr,pk=left?pl:pr;
            double rstar=qq[0]*(sk-vk)/(sk-sm);
            std::array<double,8> star{};
            star[0]=rstar;
            for(int k=1;k<4;k++)star[k]=rstar*(k==normal?sm:qq[k]);
            star[4]=rstar*(s[4]/qq[0]+(sm-vk)*(sm+pk/(qq[0]*(sk-vk))));
            for(int k=5;k<8;k++)star[k]=rstar*qq[k];
            double estar=star[4]-.5*(star[1]*star[1]+star[2]*star[2]+star[3]*star[3])/rstar;
            double pstar=pk+qq[0]*(sk-vk)*(sm-vk);
            if(!(rstar>1e-10 && estar>1e-10 && pstar>1e-10 && std::isfinite(estar))) {
                for(int k=0;k<8;k++)out[k]=(sr*fl[k]-sl*fr[k]+sl*sr*(ur[k]-ul[k]))/(sr-sl);
            } else for(int k=0;k<8;k++)out[k]=f[k]+sk*(star[k]-s[k]);
        }
        Cell answer{};for(int k=0;k<8;k++)answer[k]=out[k];return answer;
    }
    Totals operator_flow(const std::vector<Cell>& v) {
        primitives(v);
        flow_source.fill(0.);
        #pragma omp parallel for schedule(static)
        for(size_t i=0;i<n;i++)rhs[i].fill(0.f);
        Totals bd{};
        for(int ax=0;ax<3;ax++) {
            int ex=ax==0,ey=ax==1,ez=ax==2;
            double d=ax==0?cfg.dx:(ax==1?cfg.dy:cfg.dz);
            int fx=nx+ex,fy=ny+ey,fz=nz+ez;
            ptrdiff_t offset=ex+ptrdiff_t(ey)*gx+ptrdiff_t(ez)*gx*gy;
            #pragma omp parallel for collapse(2) schedule(static)
            for(int z=0;z<fz;z++)for(int y=0;y<fy;y++)for(int x=0;x<fx;x++) {
                size_t ir=qi(x+2,y+2,z+2),il=ir-offset;
                Cell l=q[il],r=q[ir];
                if(!cfg.first_order)for(int k=0;k<8;k++) {
                    l[k]+=.5*slope(q[il-offset][k],q[il][k],q[il+offset][k]);
                    r[k]-=.5*slope(q[ir-offset][k],q[ir][k],q[ir+offset][k]);
                }
                faces[fi(x,y,z,ax)]=riemann(l,r,ax);
            }
            #pragma omp parallel for collapse(2) schedule(static)
            for(int z=0;z<nz;z++)for(int y=0;y<ny;y++)for(int x=0;x<nx;x++) {
                const auto& lo=faces[fi(x,y,z,ax)];
                const auto& hi=faces[fi(x+ex,y+ey,z+ez,ax)];
                auto& dr=rhs[id(x,y,z)];
                for(int k=0;k<8;k++)dr[k]-=(hi[k]-lo[k])/d;
            }
            double area=cfg.dx*cfg.dy*cfg.dz/d;
            if(ax==0)for(int z=0;z<nz;z++)for(int y=0;y<ny;y++)for(int k=0;k<8;k++)
                bd[k]+=area*(double(faces[fi(nx,y,z,ax)][k])-faces[fi(0,y,z,ax)][k]);
            if(ax==1)for(int z=0;z<nz;z++)for(int x=0;x<nx;x++)for(int k=0;k<8;k++)
                bd[k]+=area*(double(faces[fi(x,ny,z,ax)][k])-faces[fi(x,0,z,ax)][k]);
            if(ax==2)for(int y=0;y<ny;y++)for(int x=0;x<nx;x++)for(int k=0;k<8;k++)
                bd[k]+=area*(double(faces[fi(x,y,nz,ax)][k])-faces[fi(x,y,0,ax)][k]);
        }
        if(cfg.confinement>0) {
            #pragma omp parallel for collapse(2) schedule(static)
            for(int z=1;z<gz-1;z++)for(int y=1;y<gy-1;y++)for(int x=1;x<gx-1;x++) {
                const auto& xp=q[qi(x+1,y,z)];const auto& xm=q[qi(x-1,y,z)];
                const auto& yp=q[qi(x,y+1,z)];const auto& ym=q[qi(x,y-1,z)];
                const auto& zp=q[qi(x,y,z+1)];const auto& zm=q[qi(x,y,z-1)];
                auto& w=curl[qi(x,y,z)];
                w[0]=(yp[3]-ym[3])/(2*cfg.dy)-(zp[2]-zm[2])/(2*cfg.dz);
                w[1]=(zp[1]-zm[1])/(2*cfg.dz)-(xp[3]-xm[3])/(2*cfg.dx);
                w[2]=(xp[2]-xm[2])/(2*cfg.dx)-(yp[1]-ym[1])/(2*cfg.dy);
                w[3]=std::sqrt(double(w[0])*w[0]+double(w[1])*w[1]+double(w[2])*w[2]);
            }
            double fxsum=0,fysum=0,fzsum=0,worksum=0;
            double h=std::min({cfg.dx,cfg.dy,cfg.dz});
            #pragma omp parallel for collapse(2) reduction(+:fxsum,fysum,fzsum,worksum) schedule(static)
            for(int z=0;z<nz;z++)for(int y=0;y<ny;y++)for(int x=0;x<nx;x++) {
                int xx=x+2,yy=y+2,zz=z+2;
                const auto& w=curl[qi(xx,yy,zz)];const auto& pv=q[qi(xx,yy,zz)];
                double gx=(curl[qi(xx+1,yy,zz)][3]-curl[qi(xx-1,yy,zz)][3])/(2*cfg.dx);
                double gy=(curl[qi(xx,yy+1,zz)][3]-curl[qi(xx,yy-1,zz)][3])/(2*cfg.dy);
                double gz=(curl[qi(xx,yy,zz+1)][3]-curl[qi(xx,yy,zz-1)][3])/(2*cfg.dz);
                double length=std::sqrt(gx*gx+gy*gy+gz*gz);
                double scale=length>1e-12?cfg.confinement*h*pv[0]/length:0.;
                double fx=scale*(gy*w[2]-gz*w[1]);
                double fy=scale*(gz*w[0]-gx*w[2]);
                double fz=scale*(gx*w[1]-gy*w[0]);
                double work=fx*pv[1]+fy*pv[2]+fz*pv[3];
                auto& dr=rhs[id(x,y,z)];dr[1]+=fx;dr[2]+=fy;dr[3]+=fz;dr[4]+=work;
                fxsum+=fx;fysum+=fy;fzsum+=fz;worksum+=work;
            }
            double dv=cfg.dx*cfg.dy*cfg.dz;
            flow_source[1]=fxsum*dv;flow_source[2]=fysum*dv;flow_source[3]=fzsum*dv;flow_source[4]=worksum*dv;
        }
        return bd;
    }
    double inverse_dt(const std::vector<Cell>& v) {
        double result=0.;
        #pragma omp parallel for reduction(max:result) schedule(static)
        for(size_t i=0;i<n;i++) {
            const auto& s=v[i];double rho=s[0], inv=1/rho;
            double ke=.5*(double(s[1])*s[1]+double(s[2])*s[2]+double(s[3])*s[3])*inv;
            double p=cfg.pressure?(cfg.gamma-1)*(s[4]-ke):cfg.pressure_ambient;
            double c=std::sqrt(cfg.gamma*p*inv);
            double rate=(std::abs(s[1])*inv+c)/cfg.dx+(std::abs(s[2])*inv+c)/cfg.dy+(std::abs(s[3])*inv+c)/cfg.dz;
            result=std::max(result,rate);
        }
        return result;
    }
    bool valid(const std::vector<Cell>& v) {
        int ok=1;
        #pragma omp parallel for reduction(min:ok) schedule(static)
        for(size_t i=0;i<n;i++) {
            const auto& s=v[i];double rho=s[0];
            for(int k=0;k<8;k++)if(!std::isfinite(s[k]))ok=0;
            if(!(rho>1e-6))ok=0;
            double ei=s[4]-.5*(double(s[1])*s[1]+double(s[2])*s[2]+double(s[3])*s[3])/rho;
            if(!(ei>1e-6))ok=0;
            for(int k=5;k<8;k++)if(s[k]<-1e-7 || s[k]>rho*1.00001)ok=0;
            if(s[5]+s[6]+s[7]>rho*1.00001)ok=0;
        }
        return ok;
    }
    Totals source_step(std::vector<Cell>& v,double dt) {
        Totals added{};
        if(!cfg.source)return added;
        double de=0,dmy=0,df=0,doo=0,ds=0;
        double dv=cfg.dx*cfg.dy*cfg.dz;
        #pragma omp parallel for reduction(+:de,dmy,df,doo,ds) schedule(static)
        for(size_t i=0;i<n;i++) {
            auto& s=v[i];double rho=s[0], inv=1/rho;
            double eold=s[4],myold=s[2];
            double ke=.5*(double(s[1])*s[1]+double(s[2])*s[2]+double(s[3])*s[3])*inv;
            double temp=(cfg.gamma-1)*(s[4]-ke)*inv;
            double activation=std::clamp((temp-cfg.ignition)/(cfg.active-cfg.ignition),0.,1.);
            activation=activation*activation*(3-2*activation);
            double burn=std::min(std::max(double(s[5]),0.),std::max(double(s[6]),0.)/cfg.oxygen_ratio)*(-std::expm1(-cfg.rate*activation*dt));
            float oldf=s[5],oldo=s[6],olds=s[7];
            s[5]-=burn;s[6]-=cfg.oxygen_ratio*burn;s[7]+=cfg.soot_yield*burn;
            s[4]+=cfg.heat*burn;
            // Thermal radiation/mixing loss is a documented relaxation closure.
            double excess=std::max(double(s[4])-ke-rho/(cfg.gamma-1),0.);
            if(cfg.cooling>0)s[4]-=excess*(-std::expm1(-dt/cfg.cooling));
            // Background-subtracted buoyancy keeps uniform ambient gas stationary.
            double impulse=dt*cfg.gravity*(cfg.rho_ambient-rho);
            s[2]+=impulse;
            s[4]+=.5*(myold+s[2])*impulse*inv;
            de+=double(s[4])-eold;dmy+=double(s[2])-myold;
            df+=double(s[5])-oldf;doo+=double(s[6])-oldo;ds+=double(s[7])-olds;
        }
        added[2]=dmy*dv;added[4]=de*dv;added[5]=df*dv;added[6]=doo*dv;added[7]=ds*dv;
        return added;
    }
    double advance(double requested_dt) {
        double dt=requested_dt;
        for(int retry=0;retry<14;retry++) {
            a=u;
            Totals sa=source_step(a,.5*dt);
            double stage_rate=inverse_dt(a);
            if(dt*stage_rate>cfg.cfl*1.000001){dt*=.95*cfg.cfl/(dt*stage_rate);rejects++;continue;}
            Totals ba=operator_flow(a), fa=flow_source;
            #pragma omp parallel for schedule(static)
            for(size_t i=0;i<n;i++)for(int k=0;k<8;k++)b[i][k]=a[i][k]+dt*rhs[i][k];
            if(!valid(b)){dt*=.5;rejects++;continue;}
            stage_rate=std::max(stage_rate,inverse_dt(b));
            if(dt*stage_rate>cfg.cfl*1.000001){dt*=.95*cfg.cfl/(dt*stage_rate);rejects++;continue;}
            Totals bb=operator_flow(b), fb=flow_source;
            #pragma omp parallel for schedule(static)
            for(size_t i=0;i<n;i++)for(int k=0;k<8;k++)b[i][k]=.5*(double(a[i][k])+b[i][k]+dt*rhs[i][k]);
            if(!valid(b)){dt*=.5;rejects++;continue;}
            Totals sb=source_step(b,.5*dt);
            if(!valid(b)){dt*=.5;rejects++;continue;}
            for(int k=0;k<8;k++){boundary[k]+=.5*dt*(ba[k]+bb[k]);sources[k]+=sa[k]+sb[k]+.5*dt*(fa[k]+fb[k]);}
            // Correct only negative passive roundoff; measure even this tiny change.
            for(auto& c:b)for(int k=5;k<8;k++)if(c[k]<0){tiny_correction[k]-=c[k]*cfg.dx*cfg.dy*cfg.dz;c[k]=0;}
            u.swap(b);t+=dt;steps++;max_cfl=std::max(max_cfl,dt*stage_rate);return dt;
        }
        throw std::runtime_error("Could not find positive finite timestep after fourteen retries");
    }
    void snapshot(int index) {
        char suffix[64];std::snprintf(suffix,sizeof suffix,"/state_%04d.raw",index);
        std::string final_path=cfg.output+suffix,partial_path=final_path+".partial";
        std::ofstream f(partial_path,std::ios::binary);
        f.write(reinterpret_cast<const char*>(u.data()),n*sizeof(Cell));
        if(!f)throw std::runtime_error("Failed writing snapshot");
        f.close();
        if(std::rename(partial_path.c_str(),final_path.c_str()))throw std::runtime_error("Failed publishing snapshot");
        diagnostics(index);
    }
    void diagnostics(int index) {
        Totals now=sum(u);
        double minrho=1e100,maxrho=0,minp=1e100,maxp=0,maxt=0,maxspeed=0,ke=0;
        double sootmass=0,cx=0,cy=0,cz=0,radial=0,material_radius2=0,material_mass=0;
        double minspecies=1e100;
        for(int z=0;z<nz;z++)for(int y=0;y<ny;y++)for(int x=0;x<nx;x++) {
            const auto& s=u[id(x,y,z)];double rho=s[0], inv=1/rho;
            double kin=.5*(double(s[1])*s[1]+double(s[2])*s[2]+double(s[3])*s[3])*inv;
            double p=(cfg.gamma-1)*(s[4]-kin);ke+=kin;
            minrho=std::min(minrho,rho);maxrho=std::max(maxrho,rho);minp=std::min(minp,p);maxp=std::max(maxp,p);
            maxt=std::max(maxt,p*inv);maxspeed=std::max(maxspeed,std::sqrt(2*kin*inv));
            for(int k=5;k<8;k++)minspecies=std::min(minspecies,double(s[k]));
            double xx=-6+(x+.5)*cfg.dx,yy=-1+(y+.5)*cfg.dy,zz=-6+(z+.5)*cfg.dz;
            sootmass+=s[7];cx+=s[7]*xx;cy+=s[7]*yy;cz+=s[7]*zz;
            double r=std::sqrt(xx*xx+(yy-1)*(yy-1)+zz*zz);
            if(r>1e-8 && r<4)radial+=(xx*s[1]+(yy-1)*s[2]+zz*s[3])/r;
            double material=s[5]+s[7]/cfg.soot_yield;
            material_radius2+=material*r*r;material_mass+=material;
        }
        double dv=cfg.dx*cfg.dy*cfg.dz;
        double radius=material_mass>0?std::sqrt(material_radius2/material_mass):0.;
        if(sootmass<=0){sootmass=1;cx=cy=cz=0.;}
        std::ofstream f(cfg.output+"/diagnostics.jsonl",std::ios::app);
        f<<std::setprecision(12)<<"{\"index\":"<<index<<",\"time\":"<<t<<",\"steps\":"<<steps
         <<",\"rejected_steps\":"<<rejects<<",\"max_cfl\":"<<max_cfl<<",\"rho_min\":"<<minrho
         <<",\"rho_max\":"<<maxrho<<",\"pressure_min\":"<<minp<<",\"pressure_max\":"<<maxp
         <<",\"temperature_max\":"<<maxt<<",\"speed_max\":"<<maxspeed<<",\"kinetic_energy\":"<<ke*dv
         <<",\"radial_momentum_r4\":"<<radial*dv<<",\"material_rms_radius\":"<<radius
         <<",\"species_min\":"<<minspecies<<",\"soot_centroid\":["<<cx/sootmass<<","<<cy/sootmass<<","<<cz/sootmass<<"]";
        auto arr=[&](const char* name,const Totals& val){f<<",\""<<name<<"\":[";for(int k=0;k<8;k++){if(k)f<<",";f<<val[k];}f<<"]";};
        Totals error{};for(int k=0;k<8;k++)error[k]=now[k]-initial[k]+boundary[k]-sources[k]-tiny_correction[k];
        arr("totals",now);arr("initial_totals",initial);arr("boundary_outflow_integral",boundary);arr("source_integral",sources);arr("roundoff_correction",tiny_correction);arr("conservation_residual",error);
        f<<",\"wall_seconds\":"<<elapsed<<"}\n";f.flush();
        std::cout<<"t="<<std::fixed<<std::setprecision(4)<<t<<" steps="<<steps<<" rejected="<<rejects
         <<" CFL="<<max_cfl<<" rho="<<minrho<<".."<<maxrho<<" T="<<maxt<<" KE="<<ke*dv
         <<" radius="<<radius<<" mass_res="<<std::scientific<<error[0]<<std::endl;
    }
};

int main(int argc,char** argv) {
    try {
        for(int i=1;i<argc;i++) {
            std::string flag=argv[i];
            auto next=[&](){if(++i>=argc)throw std::runtime_error("Missing value for "+flag);return argv[i];};
            if(flag=="--input")cfg.input=next();else if(flag=="--output")cfg.output=next();
            else if(flag=="--shape"){cfg.nx=std::atoi(next());cfg.ny=std::atoi(next());cfg.nz=std::atoi(next());}
            else if(flag=="--spacing"){cfg.dx=std::atof(next());cfg.dy=std::atof(next());cfg.dz=std::atof(next());}
            else if(flag=="--end")cfg.t_end=std::atof(next());else if(flag=="--initial-time")cfg.initial_time=std::atof(next());
            else if(flag=="--output-dt")cfg.output_dt=std::atof(next());else if(flag=="--threads")cfg.threads=std::atoi(next());
            else if(flag=="--gravity")cfg.gravity=std::atof(next());else if(flag=="--cooling")cfg.cooling=std::atof(next());
            else if(flag=="--rate")cfg.rate=std::atof(next());else if(flag=="--heat")cfg.heat=std::atof(next());
            else if(flag=="--cfl")cfg.cfl=std::atof(next());else if(flag=="--gamma")cfg.gamma=std::atof(next());
            else if(flag=="--max-dt")cfg.max_dt=std::atof(next());
            else if(flag=="--confinement")cfg.confinement=std::atof(next());
            else if(flag=="--ignition")cfg.ignition=std::atof(next());else if(flag=="--active")cfg.active=std::atof(next());
            else if(flag=="--oxygen-ratio")cfg.oxygen_ratio=std::atof(next());else if(flag=="--soot-yield")cfg.soot_yield=std::atof(next());
            else if(flag=="--pressure-off")cfg.pressure=false;else if(flag=="--no-sources")cfg.source=false;
            else if(flag=="--first-order")cfg.first_order=true;
            else throw std::runtime_error("Unknown argument "+flag);
        }
        if(cfg.input.empty()||cfg.output.empty())throw std::runtime_error("Required --input state.raw --output directory");
        omp_set_num_threads(cfg.threads);Solver solver;solver.load();
        std::ofstream(cfg.output+"/diagnostics.jsonl",std::ios::trunc).close();
        solver.snapshot(0);int output_index=1;
        auto began=std::chrono::steady_clock::now();
        while(solver.t<cfg.t_end-1e-10) {
            double target=std::min(cfg.t_end,cfg.initial_time+output_index*cfg.output_dt);
            while(solver.t<target-1e-10) {
                double dt=std::min({target-solver.t,cfg.max_dt,.99*cfg.cfl/solver.inverse_dt(solver.u)});
                solver.advance(dt);
            }
            solver.elapsed=std::chrono::duration<double>(std::chrono::steady_clock::now()-began).count();
            solver.snapshot(output_index++);
        }
        std::cout<<"Completed in "<<solver.elapsed<<" seconds."<<std::endl;
    } catch(const std::exception& e) {std::cerr<<"ERROR: "<<e.what()<<std::endl;return 1;}
}
