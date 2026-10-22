#!/usr/bin/env python3
"""Render each frame independently, with an explicit choice of field evaluation.

The accelerated cache backend skips only conservatively empty bricks of a fixed
world-space procedural field. All source sample indices and haze values remain
unchanged; grouped additions introduce tiny measured floating-point differences. It does
not interpolate animation frames or upscale images. Use direct for the exact
procedural shader, or cache for the separately audited offline approximation.
"""
import argparse,json,os,subprocess,sys,time
from pathlib import Path

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--source',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--width',type=int,default=1280);ap.add_argument('--height',type=int,default=720)
    ap.add_argument('--count',type=int,default=240);ap.add_argument('--fps',type=int,default=24)
    ap.add_argument('--workers',type=int,default=4)
    ap.add_argument('--renderer',choices=['direct','cache'],default='cache')
    ap.add_argument('--grid',type=int,nargs='+',default=[512])
    ap.add_argument('--bounds',type=float,nargs=6,default=[-9.,-14.,-9.,9.,14.,9.])
    ap.add_argument('--cache',type=Path)
    ap.add_argument('--dtype',choices=['f2','f4'],default='f4')
    a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    if not 1<=a.workers<=4:ap.error('Use 1 to 4 workers')
    if a.renderer=='cache' and (a.cache is None or not a.cache.is_file()):
        ap.error('Build the shared volume cache once before launching workers')
    jobs=[];handles=[];start=time.monotonic()
    renderer=Path(__file__).with_name('cache_fast.py' if a.renderer=='cache' else 'render.py')
    for i in range(a.workers):
        log=open(a.output/f'worker-{i}.log','w');handles.append(log)
        env=dict(os.environ,LP_NUM_THREADS=str(max(1,8//a.workers)),OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
        cmd=[sys.executable,str(renderer),str(a.source),str(a.output),'--width',str(a.width),'--height',str(a.height),'--count',str(a.count),'--fps',str(a.fps),'--start',str(i),'--stride',str(a.workers)]
        if a.renderer=='cache':cmd+=['--grid',*[str(v) for v in a.grid],'--bounds',*[str(v) for v in a.bounds],'--cache',str(a.cache),'--dtype',a.dtype]
        jobs.append(subprocess.Popen(cmd,env=env,stdout=log,stderr=subprocess.STDOUT))
    while any(j.poll() is None for j in jobs):
        n=len(list(a.output.glob('frame*.png')))
        print(json.dumps({'frames':n,'of':a.count,'elapsed_seconds':round(time.monotonic()-start,1),'workers':[j.poll() for j in jobs]}),flush=True)
        time.sleep(15)
    for h in handles:h.close()
    codes=[j.returncode for j in jobs]
    if any(c!=0 for c in codes):raise RuntimeError(f'Workers failed: {codes}')
    print(json.dumps({'complete':True,'frames':len(list(a.output.glob('frame*.png'))),'elapsed_seconds':time.monotonic()-start}),flush=True)

if __name__=='__main__':main()
