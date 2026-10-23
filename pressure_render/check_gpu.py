#!/usr/bin/env python3
"""Compile actual FragCoord passes and compare one complete GPU fluid timestep."""
import os,sys,json,time,argparse
from pathlib import Path
os.environ.setdefault('LP_NUM_THREADS','4')
os.environ.setdefault('MESA_SHADER_CACHE_DIR','/tmp/fragcoord-mesa-cache')
sys.path.insert(0,'/tmp/fragcoord-deps')
import numpy as np
import moderngl
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
from portable_gl import create_context
ROOT=Path(__file__).resolve().parent
def pack(U):
 nz,ny,nx,_=U.shape;tw,th=nx*8,ny*((nz+7)//8)
 out=np.zeros((th*2,tw*2+1,4),dtype='f4')
 for z in range(nz):
  x=(z%8)*nx;y=(z//8)*ny
  for bank in range(2):
   out[y+bank*th:y+bank*th+ny,x:x+nx]=U[z,:,:,:4]
   out[y+bank*th:y+bank*th+ny,x+tw:x+tw+nx]=U[z,:,:,4:]
 return out
def unpack(v,shape):
 nz,ny,nx,_=shape;tw=nx*8
 out=np.empty(shape,dtype='f4')
 for z in range(nz):
  x=(z%8)*nx;y=(z//8)*ny
  out[z,:,:,:4]=v[y:y+ny,x:x+nx];out[z,:,:,4:]=v[y:y+ny,x+tw:x+tw+nx]
 return out
def main():
 ap=argparse.ArgumentParser();ap.add_argument('initial',type=Path);ap.add_argument('--cpu',type=Path);ap.add_argument('--out',type=Path,default=ROOT/'gpu-check.json');ap.add_argument('--steps',type=int,default=1);ap.add_argument('--initialize',action='store_true')
 args=ap.parse_args();U=np.load(args.initial)['U'];packed=pack(U);h,w,_=packed.shape
 ctx=create_context()
 prefix='#version 330\nuniform vec2 u_resolution;uniform float u_time,u_time_delta;uniform int u_frame,u_recursion,u_max_recursion;uniform sampler2D u_pass1,u_pass2;out vec4 fragColor;\n'
 vs='#version 330\nin vec2 position;void main(){gl_Position=vec4(position,0,1);}'
 common=(ROOT/'fragcoord/common.glsl').read_text()
 programs={}
 for name in ['simulation','shading','main']:
  programs[name]=ctx.program(vertex_shader=vs,fragment_shader=prefix+common+(ROOT/f'fragcoord/{name}.glsl').read_text())
 p=programs['simulation'];vbo=ctx.buffer(np.array([-1,-1,3,-1,-1,3],dtype='f4').tobytes());vao=ctx.simple_vertex_array(p,vbo,'position')
 tex=[ctx.texture((w,h),4,packed.tobytes(),dtype='f4') for _ in range(2)]
 for t in tex:t.filter=(moderngl.NEAREST,moderngl.NEAREST)
 fb=[ctx.framebuffer(color_attachments=[t]) for t in tex]
 p['u_pass1'].value=0;p['u_frame'].value=0 if args.initialize else 1
 start=time.monotonic()
 stages=1 if args.initialize else args.steps*2
 for i in range(stages):
  if 'u_recursion' in p:p['u_recursion'].value=i%2
  tex[i%2].use(0);fb[(i+1)%2].use();vao.render();ctx.finish()
 arr=np.frombuffer(tex[stages%2].read(),dtype='f4').reshape(h,w,4);out=unpack(arr,U.shape)
 assert np.isfinite(out).all(),'Nonfinite GPU state'
 args.out.parent.mkdir(exist_ok=True,parents=True);np.save(args.out.with_suffix('.npy'),out)
 result={'compiled':['Common + '+k for k in programs],'grid':list(U.shape),'seconds':time.monotonic()-start,'stages':stages,'finite':bool(np.isfinite(out).all()),'renderer':ctx.info.get('GL_RENDERER')}
 if args.cpu or args.initialize:
  reference=U if args.initialize else np.load(args.cpu)['U']
  delta=out.astype('f8')-reference
  result['channel_max_absolute_error']=np.max(abs(delta),axis=(0,1,2)).tolist()
  result['channel_rms_error']=np.sqrt(np.mean(delta**2,axis=(0,1,2))).tolist()
  result['max_absolute_error']=float(np.max(abs(delta)))
 args.out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
if __name__=='__main__':main()
