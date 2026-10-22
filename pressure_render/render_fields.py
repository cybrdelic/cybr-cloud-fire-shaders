#!/usr/bin/env python3
"""Render evolving conservative fluid fields. No animated envelope or density warp.

Input: NPZ with U[z,y,x,8] = rho,mx,my,mz,E,rhoFuel,rhoOx,rhoSoot,
or a raw float32 array of that shape and --size N. All spatial detail comes
from the simulation. Lighting uses a finite-volume shadow sweep, soot
emission, and a documented local diffusion approximation to fire lighting.
"""
import argparse, hashlib, json, os, sys, time
from pathlib import Path
os.environ.setdefault('LP_NUM_THREADS','4')
os.environ.setdefault('MESA_SHADER_CACHE_DIR','/tmp/fragcoord-mesa-cache')
sys.path.insert(0,'/tmp/fragcoord-deps')
import numpy as np
from scipy.ndimage import gaussian_filter, shift
from PIL import Image
import moderngl

VERTEX = '#version 330\nin vec2 position;void main(){gl_Position=vec4(position,0,1);}'
FRAGMENT = '''#version 330
uniform sampler3D volume;
uniform vec2 resolution;
uniform vec3 domainMin,domainMax,eye,target;
uniform float stepSize,exposure;
out vec4 color;
vec3 aces(vec3 x){return clamp((x*(2.51*x+.03))/(x*(2.43*x+.59)+.14),0.,1.);}
void main(){
 vec3 w=normalize(target-eye),u=normalize(cross(w,vec3(0,1,0))),v=cross(u,w);
 vec2 q=(gl_FragCoord.xy-.5*resolution)/resolution.y;
 vec3 rd=normalize(w*1.75+u*q.x+v*q.y);
 vec3 ia=(domainMin-eye)/rd,ib=(domainMax-eye)/rd;
 vec3 nearV=min(ia,ib),farV=max(ia,ib);
 float a=max(max(nearV.x,nearV.y),nearV.z),b=min(min(farV.x,farV.y),farV.z);
 vec3 sky=mix(vec3(.24,.29,.34),vec3(.12,.19,.27),smoothstep(-.2,.5,rd.y));
 vec3 lightDir=normalize(vec3(-.5,.85,-.35));
 sky+=vec3(.18,.16,.12)*pow(max(dot(rd,lightDir),0.),12.);
 float trans=1.;vec3 sum=vec3(0);
 if(b>max(a,0.)){
  a=max(a,0.);int count=int(ceil((b-a)/stepSize));float ds=(b-a)/float(count);
  for(int i=0;i<1800;i++){
   if(i>=count||trans<.001)break;
   vec3 p=eye+rd*(a+(float(i)+.5)*ds);
   vec4 s=texture(volume,(p-domainMin)/(domainMax-domainMin));
   float alpha=1.-exp(-s.a*ds);
   sum+=trans*alpha*s.rgb;trans*=1.-alpha;
  }
 }
 vec3 hdr=sum+trans*sky;
 vec3 mapped=aces(hdr*exposure);
 color=vec4(pow(mapped,vec3(1./2.2)),1);
}
'''

def load_state(path,size=None):
    if path.suffix=='.npz':
        with np.load(path) as d:
            if 'U' in d: return np.array(d['U'],dtype='f4')
            if 'state' in d: return np.array(d['state'],dtype='f4')
            return np.stack([d[k] for k in ['rho','mx','my','mz','E','fuel','oxidizer','soot']],-1).astype('f4')
    return np.fromfile(path,dtype='<f4').reshape(size,size,size,8)

def blackbody(T):
    # Planck radiance sampled at RGB representative wavelengths; the intensity
    # scale is an exposure/art-direction parameter, not a measured radiance.
    waves=np.array([.650,.550,.450],dtype='f4')*1e-6
    tt=np.maximum(T,300)[...,None]
    z=0.014387769/(tt*waves)
    bb=1./(waves**5*np.expm1(np.clip(z,0,80)))
    reference=1./((650e-9)**5*np.expm1(.014387769/(1800*650e-9)))
    return (bb/reference).astype('f4')

def shade(U,cell,gamma=1.3,ambient_pressure=1.,ambient_density=1.,soot_gain=38.,emission_gain=8.):
    rho=np.maximum(U[...,0],1e-5)
    kinetic=.5*np.sum(U[...,1:4]**2,axis=-1)/rho
    pressure=np.maximum((gamma-1)*(U[...,4]-kinetic),1e-5)
    temperature=300*(pressure/rho)/(ambient_pressure/ambient_density)
    soot=np.maximum(U[...,7],0)
    sigma=soot*soot_gain
    # Visible extinction and emission follow transported soot. Clear ambient
    # gas remains clear; no artificial envelope or animated opacity is added.
    sigma=np.where(sigma<1e-5,0,sigma)
    ny=U.shape[1]
    tau=np.zeros_like(sigma)
    cell=np.broadcast_to(cell,(3,))
    dz,dx=(-.35/.85)*(cell[1]/cell[2]),(-.5/.85)*(cell[1]/cell[0])
    ds=cell[1]*np.sqrt(1+(.5/.85)**2+(.35/.85)**2)
    for y in range(ny-2,-1,-1):
        above=shift(tau[:,y+1,:]+sigma[:,y+1,:]*ds,
                    shift=(-dz,-dx),order=1,mode='constant',cval=0,prefilter=False)
        tau[:,y,:]=above
    sunlight=np.exp(-np.minimum(tau,30))
    thermal=blackbody(temperature)*emission_gain
    thermal*=np.clip((temperature[...,None]-650)/300,0,1)
    # Approximate short-range multiple scattering from nearby emissive soot.
    # This changes only illumination; it never changes/moves the simulated field.
    glowing=thermal*np.clip(sigma[...,None]*float(cell.min()),0,1)
    indirect=gaussian_filter(glowing,sigma=(2.4,2.4,2.4,0),mode='constant')*.65
    source=thermal+indirect
    source+=np.array([.006,.008,.011],dtype='f4')
    source+=sunlight[...,None]*np.array([.080,.070,.055],dtype='f4')
    volume=np.concatenate([source,sigma[...,None]],axis=-1).astype('f4')
    assert np.isfinite(volume).all(), 'Nonfinite shading volume'
    stats={'density_min':float(rho.min()),'density_max':float(rho.max()),
           'pressure_min':float(pressure.min()),'pressure_max':float(pressure.max()),
           'temperature_max_kelvin_scaled':float(temperature.max()),
           'soot_max':float(soot.max()),'soot_sum':float(soot.sum()),
           'sigma_max':float(sigma.max()),'emission_max':float(thermal.max())}
    return volume,stats

class Renderer:
    def __init__(self,width,height,domain_min,domain_max,eye,target,step,exposure):
        self.width,self.height=width,height
        self.ctx=moderngl.create_standalone_context(backend='egl')
        self.program=self.ctx.program(vertex_shader=VERTEX,fragment_shader=FRAGMENT)
        p=self.program
        for k,v in {'resolution':(width,height),'domainMin':domain_min,'domainMax':domain_max,
                    'eye':eye,'target':target,'stepSize':step,'exposure':exposure,'volume':0}.items():
            p[k].value=v
        self.vbo=self.ctx.buffer(np.array([-1,-1,3,-1,-1,3],dtype='f4').tobytes())
        self.vao=self.ctx.simple_vertex_array(p,self.vbo,'position')
        self.fbo=self.ctx.simple_framebuffer((width,height),components=4,dtype='f4')
        self.texture=None
    def draw(self,volume):
        nz,ny,nx,_=volume.shape
        if self.texture is None:
            self.texture=self.ctx.texture3d((nx,ny,nz),4,volume.tobytes(),dtype='f4')
            self.texture.filter=(moderngl.LINEAR,moderngl.LINEAR)
            self.texture.repeat_x=self.texture.repeat_y=self.texture.repeat_z=False
        else:self.texture.write(volume.tobytes())
        self.texture.use(0);self.fbo.use();self.vao.render();self.ctx.finish()
        pixels=np.frombuffer(self.fbo.read(components=4,dtype='f4'),dtype='f4').reshape(self.height,self.width,4)
        if not np.isfinite(pixels).all():raise ValueError('Nonfinite render')
        return Image.fromarray((np.clip(pixels[::-1,:,:3],0,1)*255+.5).astype('uint8'))

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('input',type=Path);ap.add_argument('output',type=Path)
    ap.add_argument('--size',type=int,default=64)
    ap.add_argument('--length',type=float,default=12)
    ap.add_argument('--width',type=int,default=640);ap.add_argument('--height',type=int,default=360)
    ap.add_argument('--gamma',type=float,default=1.3);ap.add_argument('--pressure',type=float,default=1)
    ap.add_argument('--bounds',type=float,nargs=6,default=[-6,6,-1,13,-6,6])
    ap.add_argument('--soot',type=float,default=38);ap.add_argument('--emission',type=float,default=8)
    ap.add_argument('--exposure',type=float,default=1)
    ap.add_argument('--eye',type=float,nargs=3);ap.add_argument('--target',type=float,nargs=3)
    args=ap.parse_args();start=time.monotonic()
    U=load_state(args.input,args.size);L=args.length
    bounds=np.array(args.bounds).reshape(3,2);extent=bounds[:,1]-bounds[:,0]
    cell=extent/np.array(U.shape[:3][::-1])
    volume,stats=shade(U,cell,args.gamma,args.pressure,soot_gain=args.soot,emission_gain=args.emission)
    eye=args.eye or [L*.05,L*.42,-L*1.2]
    target=args.target or [0,L*.4,0]
    r=Renderer(args.width,args.height,bounds[:,0],bounds[:,1],eye,target,float(cell.min())*.4,args.exposure)
    im=r.draw(volume);args.output.parent.mkdir(exist_ok=True,parents=True);im.save(args.output)
    stats.update({'input':str(args.input),'input_sha256':hashlib.sha256(args.input.read_bytes()).hexdigest(),
                  'elapsed':time.monotonic()-start,'dimensions':[args.width,args.height],
                  'grid_shape':list(U.shape),'renderer':r.ctx.info.get('GL_RENDERER'),'eye':eye,'target':target})
    args.output.with_suffix('.json').write_text(json.dumps(stats,indent=2)+'\n')
    print(json.dumps(stats))
if __name__=='__main__':main()
