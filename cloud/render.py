#!/usr/bin/env python3
"""Render the delivered GLSL without image synthesis or frame interpolation."""
import os
os.environ.setdefault('LP_NUM_THREADS','2')
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('MESA_SHADER_CACHE_DIR','/tmp/cloud-v15-mesa-cache')
import sys
from pathlib import Path
for dep in ['/tmp/fragcoord-py','/tmp/fragcoord-deps']:
    if Path(dep,'moderngl').exists():
        sys.path.insert(0,dep);break
import argparse,hashlib,json,time
import moderngl
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
from portable_gl import create_context
import numpy as np
from PIL import Image,ImageDraw

PREFIX='''#version 330
uniform vec2 u_resolution;
uniform float u_time;
out vec4 fragColor;
'''
VERTEX='''#version 330
in vec2 position;
void main(){gl_Position=vec4(position,0,1);}
'''

class Renderer:
    def __init__(self,source,width=640,height=360):
        self.width,self.height=width,height
        self.ctx=create_context(require=330)
        self.program=self.ctx.program(vertex_shader=VERTEX,fragment_shader=PREFIX+source)
        self.vbo=self.ctx.buffer(np.array([-1,-1,3,-1,-1,3],dtype='f4').tobytes())
        self.vao=self.ctx.vertex_array(self.program,[(self.vbo,'2f','position')])
        self.fbo=self.ctx.simple_framebuffer((width,height),components=4,dtype='f4')
        self.fbo.use()
        if 'u_resolution' in self.program:self.program['u_resolution'].value=(width,height)
    def draw(self,t):
        start=time.monotonic()
        if 'u_time' in self.program:self.program['u_time'].value=t
        self.vao.render(moderngl.TRIANGLES)
        a=np.frombuffer(self.fbo.read(components=4,dtype='f4',alignment=1),dtype='f4').reshape(self.height,self.width,4)[::-1].copy()
        if not np.isfinite(a).all():raise RuntimeError(f'Nonfinite output at {t}')
        rgb=np.rint(np.clip(a[:,:,:3],0,1)*255).astype('uint8')
        record={'time':t,'render_seconds':time.monotonic()-start,'all_finite':True,'min':float(a.min()),'max':float(a.max()),'mean_rgb':a[:,:,:3].mean(axis=(0,1)).tolist(),'pixel_sha256':hashlib.sha256(rgb.tobytes()).hexdigest()}
        return Image.fromarray(rgb),record

def main():
    ap=argparse.ArgumentParser();ap.add_argument('source',type=Path);ap.add_argument('output',type=Path)
    ap.add_argument('--width',type=int,default=640);ap.add_argument('--height',type=int,default=360)
    ap.add_argument('--times',type=float,nargs='+',default=[0,3,6,9])
    ap.add_argument('--count',type=int);ap.add_argument('--fps',type=float,default=24)
    ap.add_argument('--start',type=int,default=0);ap.add_argument('--stride',type=int,default=1)
    ap.add_argument('--shutter-samples',type=int,default=1)
    args=ap.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    source=args.source.read_text();rh=hashlib.sha256(source.encode()).hexdigest()
    r=Renderer(source,args.width,args.height)
    indices=range(args.start,args.count,args.stride) if args.count is not None else range(len(args.times))
    records=[]
    for i in indices:
        t=i/args.fps if args.count is not None else args.times[i]
        target=args.output/f'frame{i:06d}.png';meta=target.with_suffix('.json')
        if target.exists() and meta.exists():
            old=json.loads(meta.read_text())
            if old['source_sha256']==rh and old['width']==args.width and old['height']==args.height and old['time']==t and old.get('shutter_samples',1)==args.shutter_samples:
                records.append(old);continue
        im,record=r.draw(t)
        if args.shutter_samples>1:
            # Actual separately shaded exposure samples; no frame interpolation.
            total=np.array(im,dtype='f4')
            for k in range(1,args.shutter_samples):
                st=t+(k/args.shutter_samples)*.5/args.fps
                sample,_=r.draw(st);total+=np.array(sample,dtype='f4')
            im=Image.fromarray(np.rint(total/args.shutter_samples).astype('uint8'))
            record['pixel_sha256']=hashlib.sha256(im.tobytes()).hexdigest()
        im.save(target,compress_level=1)
        record.update(index=i,width=args.width,height=args.height,source_sha256=rh,shutter_samples=args.shutter_samples,renderer=r.ctx.info['GL_RENDERER'])
        meta.write_text(json.dumps(record,indent=2)+'\n');records.append(record)
        print(json.dumps(record),flush=True)
    if args.count is None:
        tw=min(args.width,640);th=round(args.height*tw/args.width)
        sheet=Image.new('RGB',(tw*2,(th+26)*((len(records)+1)//2)),(16,20,28));d=ImageDraw.Draw(sheet)
        for n,rec in enumerate(records):
            im=Image.open(args.output/f"frame{rec['index']:06d}.png");im.thumbnail((tw,th));x=n%2*tw;y=n//2*(th+26)
            sheet.paste(im,(x,y));d.text((x+8,y+th+6),f"{rec['time']:.2f}s",fill='white')
        sheet.save(args.output/'contact.jpg',quality=94)
    (args.output/f'render-{args.start}.json').write_text(json.dumps(records,indent=2)+'\n')

if __name__=='__main__':main()
