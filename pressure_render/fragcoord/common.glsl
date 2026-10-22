// Reactive compressible Euler. State is stored in a 2D atlas; no Pro buffer required.
// Common tab. Simulation: 769x672 RGBA32F, nearest, 20 recursions.
// Shading: 384x336 RGBA16F, linear, 1 recursion. Main: display resolution.
const ivec3 GRID=ivec3(48,56,48);
const ivec2 TILE=ivec2(384,336);
const vec3 BMIN=vec3(-6,-1,-6),BMAX=vec3(6,13,6);
const float GAMMA=1.3,DT=.0025;
const float HEAT=500.,RATE=3.5,COOL=8.,BUOY=.35,CONFINEMENT=2.;
const float SOOT_GAIN=1600.,EMISSION_GAIN=.6;
struct State{vec4 a;vec4 b;};
State addS(State x,State y){return State(x.a+y.a,x.b+y.b);}
State subS(State x,State y){return State(x.a-y.a,x.b-y.b);}
State mulS(State x,float a){return State(x.a*a,x.b*a);}
ivec2 address(ivec3 p){p=clamp(p,ivec3(0),GRID-1);return ivec2((p.z%8)*GRID.x+p.x,(p.z/8)*GRID.y+p.y);}
ivec3 voxel(ivec2 p){return ivec3(p.x%GRID.x,p.y%GRID.y,(p.y/GRID.y)*8+p.x/GRID.x);}
State readS(sampler2D tex,ivec3 p,int bank){
 ivec2 c=address(p)+ivec2(0,bank*TILE.y);
 return State(texelFetch(tex,c,0),texelFetch(tex,c+ivec2(TILE.x,0),0));
}
State primitive(State s){
 float rho=s.a.x;
 return State(vec4(rho,s.a.yzw/rho),vec4((GAMMA-1.)*(s.b.x-.5*dot(s.a.yzw,s.a.yzw)/rho),s.b.yzw/rho));
}
State conserved(State q){
 float rho=q.a.x;
 return State(vec4(rho,q.a.yzw*rho),vec4(q.b.x/(GAMMA-1.)+.5*rho*dot(q.a.yzw,q.a.yzw),q.b.yzw*rho));
}
State sourceStep(State s,float dt){
 float rho=s.a.x,ke=.5*dot(s.a.yzw,s.a.yzw)/rho;
 float T=(GAMMA-1.)*(s.b.x-ke)/rho;
 float activation=smoothstep(1.3,2.,T);
 float burn=min(max(s.b.y,0.),max(s.b.z,0.)/3.)*(1.-exp(-RATE*activation*dt));
 s.b.y-=burn;s.b.z-=3.*burn;s.b.w+=.22*burn;s.b.x+=HEAT*burn;
 s.b.x-=max(s.b.x-ke-rho/(GAMMA-1.),0.)*(1.-exp(-dt/COOL));
 float impulse=dt*BUOY*(1.-rho),old=s.a.z;
 s.a.z+=impulse;s.b.x+=.5*(old+s.a.z)*impulse/rho;
 return s;
}
vec4 minmod(vec4 a,vec4 b,vec4 c){return .25*(sign(a)+sign(b))*abs(sign(a)+sign(c))*min(abs(a),min(abs(b),abs(c)));}
State slopeS(State a,State b,State c){
 return State(minmod(1.5*(b.a-a.a),.5*(c.a-a.a),1.5*(c.a-b.a)),
              minmod(1.5*(b.b-a.b),.5*(c.b-a.b),1.5*(c.b-b.b)));
}
State riemann(State l,State r,int axis){
 State ul=conserved(l),ur=conserved(r);
 int n=axis+1;float vl=l.a[n],vr=r.a[n],pl=l.b.x,pr=r.b.x;
 float cl=sqrt(GAMMA*pl/l.a.x),cr=sqrt(GAMMA*pr/r.a.x);
 float sl=min(vl-cl,vr-cr),sr=max(vl+cl,vr+cr);
 State fl=mulS(ul,vl),fr=mulS(ur,vr);
 fl.a[n]+=pl;fr.a[n]+=pr;fl.b.x+=pl*vl;fr.b.x+=pr*vr;
 if(sl>=0.)return fl;if(sr<=0.)return fr;
 float al=l.a.x*(sl-vl),ar=r.a.x*(sr-vr);
 float sm=(pr-pl+al*vl-ar*vr)/(al-ar);
 State q=l,u=ul,f=fl;float sk=sl,vk=vl,pk=pl;
 if(sm<0.){q=r;u=ur;f=fr;sk=sr;vk=vr;pk=pr;}
 float rs=q.a.x*(sk-vk)/(sk-sm);
 State star=State(vec4(rs,rs*q.a.yzw),vec4(0,rs*q.b.yzw));
 star.a[n]=rs*sm;
 star.b.x=rs*(u.b.x/q.a.x+(sm-vk)*(sm+pk/(q.a.x*(sk-vk))));
 float ei=star.b.x-.5*dot(star.a.yzw,star.a.yzw)/rs;
 float ps=pk+q.a.x*(sk-vk)*(sm-vk);
 if(!(rs>1e-10&&ei>1e-10&&ps>1e-10))
  return mulS(addS(subS(mulS(fl,sr),mulS(fr,sl)),mulS(subS(ur,ul),sl*sr)),1./(sr-sl));
 return addS(f,mulS(subS(star,u),sk));
}
State stageRead(sampler2D tex,ivec3 p,bool halfSource){
 State s=readS(tex,p,0);if(halfSource)s=sourceStep(s,DT*.5);return primitive(s);
}
vec3 stageVelocity(sampler2D tex,ivec3 p,bool halfSource){
 vec4 a=texelFetch(tex,address(p),0);
 if(halfSource)a.z+=DT*.5*BUOY*(1.-a.x);
 return a.yzw/a.x;
}
vec4 curlAt(sampler2D tex,ivec3 p,bool halfSource){
 vec3 h=(BMAX-BMIN)/vec3(GRID);
 vec3 dx=(stageVelocity(tex,p+ivec3(1,0,0),halfSource)-stageVelocity(tex,p-ivec3(1,0,0),halfSource))/(2.*h.x);
 vec3 dy=(stageVelocity(tex,p+ivec3(0,1,0),halfSource)-stageVelocity(tex,p-ivec3(0,1,0),halfSource))/(2.*h.y);
 vec3 dz=(stageVelocity(tex,p+ivec3(0,0,1),halfSource)-stageVelocity(tex,p-ivec3(0,0,1),halfSource))/(2.*h.z);
 vec3 w=vec3(dy.z-dz.y,dz.x-dx.z,dx.y-dy.x);return vec4(w,length(w));
}
State flowRHS(sampler2D tex,ivec3 p,State center,bool halfSource){
 State d=State(vec4(0),vec4(0));
 vec3 spacing=(BMAX-BMIN)/vec3(GRID);
 for(int axis=0;axis<3;axis++){
  ivec3 e=ivec3(0);e[axis]=1;
  State mm=stageRead(tex,p-e*2,halfSource),m=stageRead(tex,p-e,halfSource);
  State a=stageRead(tex,p+e,halfSource),aa=stageRead(tex,p+e*2,halfSource);
  State sm=slopeS(mm,m,center),sc=slopeS(m,center,a),sp=slopeS(center,a,aa);
  State lo=riemann(addS(m,mulS(sm,.5)),subS(center,mulS(sc,.5)),axis);
  State hi=riemann(addS(center,mulS(sc,.5)),subS(a,mulS(sp,.5)),axis);
  d=addS(d,mulS(subS(lo,hi),1./spacing[axis]));
 }
 vec3 w=curlAt(tex,p,halfSource).xyz,gradient=vec3(0);
 for(int axis=0;axis<3;axis++){
  ivec3 e=ivec3(0);e[axis]=1;
  gradient[axis]=(curlAt(tex,p+e,halfSource).w-curlAt(tex,p-e,halfSource).w)/(2.*spacing[axis]);
 }
 float magnitude=length(gradient);
 if(magnitude>1e-12){
  vec3 force=CONFINEMENT*min(spacing.x,min(spacing.y,spacing.z))*center.a.x*cross(gradient/magnitude,w);
  d.a.yzw+=force;d.b.x+=dot(force,center.a.yzw);
 }
 return d;
}
float pocket(vec3 p,vec3 c,vec3 r,float h){vec3 d=(p-c)/r;return 1./(1.+exp(clamp(9.*(dot(d,d)-1.-.65*h),-80.,80.)));}
State initialState(ivec3 cell){
 vec3 p=BMIN+(vec3(cell)+.5)*(BMAX-BMIN)/vec3(GRID);
 float x=p.x,y=p.y,z=p.z;
 float h=.23*sin(3.7*x+1.2*y)*cos(4.2*z-.7*y)+.13*sin(8.1*z+2.8*y)*cos(7.3*x-1.5*z)+.08*sin(11.1*y+3.3*x)*cos(9.1*z+1.1*x);
 float remaining=1.;
 remaining*=1.-pocket(p,vec3(0,.93,0),vec3(.87,.60,.72),h);
 remaining*=1.-pocket(p,vec3(-.77,1.10,.08),vec3(.62,.44,.48),h);
 remaining*=1.-pocket(p,vec3(.78,1.15,-.18),vec3(.58,.52,.43),h);
 remaining*=1.-pocket(p,vec3(.14,1.49,.39),vec3(.49,.60,.49),h);
 remaining*=1.-pocket(p,vec3(-.27,.60,-.63),vec3(.57,.40,.48),h);
 remaining*=1.-pocket(p,vec3(.48,.60,.49),vec3(.53,.39,.41),h);
 float mixture=clamp((1.-remaining)*(.84+.35*h),0.,1.),rho=1.+.40*mixture;
 float fuel=clamp(.34*mixture*(1.+.55*h),0.,.49);
 vec3 d=vec3((x-.08)/.32,(y-.72)/.28,(z+.12)/.25);
 vec3 e=vec3((x+.31)/.24,(y-.83)/.24,(z-.10)/.27);
 float pressure=1.+.75*mixture+18.*exp(-pow(dot(d,d),2.))+9.*exp(-pow(dot(e,e),2.));
 return State(vec4(rho,0,0,0),vec4(pressure/(GAMMA-1.),rho*fuel,rho*.23*(1.-fuel),rho*.0015*mixture));
}
vec3 blackbody(float T){
 vec3 wl=vec3(.650,.550,.450)*1e-6;
 vec3 b=1./(pow(wl,vec3(5))*(exp(clamp(.014387769/(max(T,300.)*wl),vec3(0),vec3(80)))-1.));
 float ref=1./(pow(650e-9,5.)*(exp(.014387769/(1800.*650e-9))-1.));
 return b/ref*EMISSION_GAIN*clamp((T-650.)/300.,0.,1.);
}
