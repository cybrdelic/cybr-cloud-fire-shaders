#!/usr/bin/env python3
"""Bounded full-horizon runtime gate for the unchanged shipped GPU solver."""
import os
os.environ.setdefault('LP_NUM_THREADS','6')
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
import argparse,hashlib,json,re,sys,time
from pathlib import Path
sys.path.insert(0,'/tmp/fragcoord-deps')
import numpy as np
import moderngl
from check_gpu import pack,unpack

ROOT=Path(__file__).resolve().parent

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--end',type=float,default=4.775)
    ap.add_argument('--budget',type=float,default=240.)
    ap.add_argument('--check-every',type=int,default=10)
    ap.add_argument('--out',type=Path,default=ROOT/'gpu-full-run.json')
    args=ap.parse_args()
    began=time.monotonic()
    sources={name:(ROOT/f'fragcoord/{name}.glsl').read_text() for name in ['common','simulation','shading','main']}
    common=sources['common']
    dims=tuple(map(int,re.search(r'GRID=ivec3\((\d+),(\d+),(\d+)\)',common).groups()))
    dt=float(re.search(r'\bDT=([.\d]+)',common).group(1))
    gamma=float(re.search(r'\bGAMMA=([.\d]+)',common).group(1))
    assert dims==(48,56,48) and dt==.0025,'Gate must test shipped default'
    nx,ny,nz=dims;shape=(nz,ny,nx,8)
    zero=pack(np.zeros(shape,dtype='f4'));h,w,_=zero.shape
    target_steps=int(round(args.end/dt))
    assert abs(target_steps*dt-args.end)<1e-9
    ctx=moderngl.create_standalone_context(backend='egl')
    prefix='#version 330\nuniform vec2 u_resolution;uniform float u_time,u_time_delta;uniform int u_frame,u_recursion,u_max_recursion;uniform sampler2D u_pass1,u_pass2;out vec4 fragColor;\n'
    vs='#version 330\nin vec2 position;void main(){gl_Position=vec4(position,0,1);}'
    programs={name:ctx.program(vertex_shader=vs,fragment_shader=prefix+common+sources[name]) for name in ['simulation','shading','main']}
    p=programs['simulation']
    vbo=ctx.buffer(np.array([-1,-1,3,-1,-1,3],dtype='f4').tobytes())
    vao=ctx.simple_vertex_array(p,vbo,'position')
    tex=[ctx.texture((w,h),4,zero.tobytes(),dtype='f4') for _ in range(2)]
    for t in tex:
        t.filter=(moderngl.NEAREST,moderngl.NEAREST)
        t.repeat_x=t.repeat_y=False
    fb=[ctx.framebuffer(color_attachments=[t]) for t in tex]
    p['u_pass1'].value=0
    front=0
    def stage(frame):
        nonlocal front
        p['u_frame'].value=frame
        tex[front].use(0);fb[1-front].use();vao.render();front=1-front
    # Exactly the HTML reset path: one shader initialization pass from cleared textures.
    stage(0);ctx.finish()
    hashes=set();checks=0;completed=0;failed=None
    global_min_rho=float('inf');global_min_p=float('inf');max_cfl=0.;max_speed=0.;min_species=float('inf')
    milestones=[]
    source_hashes={k:hashlib.sha256(v.encode()).hexdigest() for k,v in sources.items()}
    result={}
    def inspect(step):
        nonlocal checks,global_min_rho,global_min_p,max_cfl,max_speed,min_species
        raw=tex[front].read()
        atlas=np.frombuffer(raw,dtype='f4').reshape(h,w,4)
        clock=float(atlas[0,w-1,0])
        if clock!=step*2:raise AssertionError(f'RK phase clock {clock} != {step*2}')
        u=unpack(atlas,shape)
        if not np.isfinite(u).all():raise AssertionError('Nonfinite GPU state')
        rho=u[...,0].astype('f8')
        mom=u[...,1:4].astype('f8')
        velocity=mom/rho[...,None]
        pressure=(gamma-1)*(u[...,4]-.5*np.sum(mom*mom,axis=-1)/rho)
        mr=float(rho.min());mp=float(pressure.min())
        if not (mr>0 and mp>0):raise AssertionError(f'Nonpositive rho/p: {mr}, {mp}')
        digest=hashlib.sha256(u.tobytes()).hexdigest()
        if digest in hashes:raise AssertionError('Repeated physical volume state')
        hashes.add(digest);checks+=1
        global_min_rho=min(global_min_rho,mr);global_min_p=min(global_min_p,mp)
        min_species=min(min_species,float(u[...,5:8].min()))
        sound=np.sqrt(gamma*pressure/rho)
        cfl=float(dt*np.max(np.sum(np.abs(velocity)+sound[...,None],axis=-1)/.25))
        max_cfl=max(max_cfl,cfl);max_speed=max(max_speed,float(np.sqrt(np.sum(velocity*velocity,axis=-1)).max()))
        if step%200==0 or step==target_steps:
            milestones.append(dict(step=step,time=step*dt,rho_min=mr,pressure_min=mp,acoustic_cfl=cfl))
    def publish(status):
        nonlocal result
        result=dict(status=status,complete=completed==target_steps and failed is None,
            passed_through_tested_horizon=failed is None,requested_time=args.end,
            tested_time=completed*dt,dt=dt,completed_steps=completed,requested_steps=target_steps,
            completed_rk_stages=completed*2,grid_xyz=list(dims),initialization='actual GLSL initialization from cleared textures',
            checked_volume_states=checks,unique_checked_volume_states=len(hashes),check_every_steps=args.check_every,
            all_checked_states_finite_positive=failed is None,minimum_density=global_min_rho,
            minimum_pressure=global_min_p,minimum_species=min_species,maximum_checked_acoustic_cfl=max_cfl,
            maximum_speed=max_speed,phase_clock_checks_passed=failed is None,
            seconds=time.monotonic()-began,budget_seconds=args.budget,renderer=ctx.info.get('GL_RENDERER'),
            software_threads=int(os.environ['LP_NUM_THREADS']),shader_sha256=source_hashes,
            compiled=['common + '+k for k in programs],milestones=milestones,error=failed,
            scope='Unmodified shipped shader bodies under an OpenGL 3.3 test prefix; simulation runtime, not browser UI or visual-quality validation.')
        tmp=args.out.with_suffix('.json.partial');tmp.write_text(json.dumps(result,indent=2)+'\n');tmp.replace(args.out)
    inspect(0);publish('running')
    last_report=time.monotonic()
    try:
        for step in range(1,target_steps+1):
            if time.monotonic()-began>=args.budget:break
            stage(step);stage(step)
            completed=step
            if step%args.check_every==0 or step==target_steps:
                ctx.finish();inspect(step)
                if time.monotonic()-last_report>=20 or step==target_steps:
                    publish('running')
                    print(json.dumps({k:result[k] for k in ['tested_time','completed_steps','seconds','minimum_density','minimum_pressure','maximum_checked_acoustic_cfl']}),flush=True)
                    last_report=time.monotonic()
        if completed%args.check_every and completed!=target_steps:
            ctx.finish();inspect(completed)
    except Exception as e:
        failed=f'{type(e).__name__}: {e}'
    publish('failed' if failed else 'complete' if completed==target_steps else 'time_budget_reached')
    print(json.dumps(result,indent=2),flush=True)

if __name__=='__main__':main()
