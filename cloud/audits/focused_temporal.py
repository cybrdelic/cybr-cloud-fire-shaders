import os,sys,time,json,hashlib
from pathlib import Path
os.environ['LP_NUM_THREADS']='2'
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from render import Renderer
import numpy as np
from PIL import Image,ImageDraw
root=ROOT;out=Path(__file__).resolve().parent;out.mkdir(parents=True,exist_ok=True)
source=(root/'cloud-flight.glsl').read_text();golf=(root/'cloud-flight.fragcoord.txt').read_text()
r=Renderer(source,48,27)
def draw(renderer,t):
 im,meta=renderer.draw(float(t));a=np.frombuffer(renderer.fbo.read(components=4,dtype='f4',alignment=1),dtype='f4').reshape(27,48,4)[::-1,:,:3].copy();return a,im,meta
indices=np.arange(187,222);ts=indices/24.
a=[];records=[]
for k,t in enumerate(ts):
 x,im,meta=draw(r,t);a.append(x);records.append(meta)
 if k%6==0:print(json.dumps({'stage':'temporal','frame':int(indices[k]),'time':float(t),'done':k+1,'total':len(ts)}),flush=True)
a=np.stack(a);delta=np.abs(np.diff(a,axis=0));d1=delta.mean(axis=(1,2,3));d2=np.abs(np.diff(a,n=2,axis=0)).mean(axis=(1,2,3))
report={'source_sha256':hashlib.sha256(source.encode()).hexdigest(),'golf_sha256':hashlib.sha256(golf.encode()).hexdigest(),'characters':len(golf),'width':48,'height':27,'fps':24,'sample_count':len(ts),'time_start':float(ts[0]),'time_end':float(ts[-1]),'all_finite':bool(np.isfinite(a).all()),'unique_float_frames':len({hashlib.sha256(x.tobytes()).hexdigest() for x in a}),'scope':'Focused exact low-resolution integration checks near the cloud fringe; does not prove absence of all high-resolution spatial or temporal aliasing.','frame_delta':{'mean':float(d1.mean()),'max_mean_abs_rgb':float(d1.max()),'max_time':float(ts[np.argmax(d1)+1]),'max_pixel_abs_rgb':float(delta.max()),'max_second_difference_mean_rgb':float(d2.max()),'second_difference_time':float(ts[np.argmax(d2)+1])}}
small=[]
for t in [8.349,8.35,8.351]:
 x,_,_=draw(r,t);small.append(x)
d=np.abs(np.diff(np.stack(small),axis=0));report['tiny_time_probe']={'times':[8.349,8.35,8.351],'delta_time':.001,'mean_abs_rgb_per_step':d.mean(axis=(1,2,3)).tolist(),'p99_abs_rgb_per_step':[float(np.percentile(z,99)) for z in d],'max_abs_rgb_per_step':d.max(axis=(1,2,3)).tolist()}
fine=source.replace('-r/64.0','-r/128.0').replace('float(i)<2e3','float(i)<4e3').replace('p+=r/32.0','p+=r/64.0').replace('exp(-g(p,6.)/11.0)','exp(-g(p,6.)/22.0)').replace('exp(-float(i)/1e3)','exp(-float(i)/2e3)')
assert fine!=source
(out/'reference-step64.glsl').write_text(fine)
f=Renderer(fine,48,27);comparisons=[]
for t in [8.125,8.416666666666666,8.708333333333334]:
 ix=int(round(t*24))-187;x=a[ix];ref,_,_=draw(f,t);er=np.abs(x-ref);mse=float(np.mean((x-ref)**2));rec={'time':float(t),'mean_abs_rgb':float(er.mean()),'p99_abs_rgb':float(np.percentile(er,99)),'max_abs_rgb':float(er.max()),'psnr_db':float(-10*np.log10(mse))};comparisons.append(rec);print(json.dumps({'stage':'finer_reference',**rec}),flush=True)
report['primary_step_reference']={'delivered_step':1/32,'reference_step':1/64,'ray_distance':62.5,'shadow_integration_unchanged':True,'samples':comparisons}
report['renderer']=r.ctx.info['GL_RENDERER']
np.savez_compressed(out/'focused-frames.npz',times=ts,frames=a)
(out/'temporal-audit.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2),flush=True)
