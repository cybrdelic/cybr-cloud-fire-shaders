#!/usr/bin/env python3
"""Stream atomically published simulation checkpoints into unique video frames."""
import os
os.environ['LP_NUM_THREADS']='1'
os.environ['OPENBLAS_NUM_THREADS']='1'
os.environ['OMP_NUM_THREADS']='1'
import argparse,hashlib,json,subprocess,time
from pathlib import Path
from render_fields import np,shade,Renderer,Image
from PIL import ImageDraw

def main():
 ap=argparse.ArgumentParser();ap.add_argument('states',type=Path);ap.add_argument('output',type=Path)
 ap.add_argument('--width',type=int,default=1280);ap.add_argument('--height',type=int,default=720)
 ap.add_argument('--count',type=int,default=192);ap.add_argument('--fps',type=int,default=24)
 ap.add_argument('--soot',type=float,default=1600);ap.add_argument('--emission',type=float,default=.6)
 ap.add_argument('--eye',type=float,nargs=3,default=[5,4.2,-10.5]);ap.add_argument('--target',type=float,nargs=3,default=[0,2.6,0])
 args=ap.parse_args();frames=args.output.with_name(args.output.stem+'-frames');frames.mkdir(exist_ok=True,parents=True)
 config={'width':args.width,'height':args.height,'count':args.count,'fps':args.fps,'soot':args.soot,'emission':args.emission,'eye':args.eye,'target':args.target,'source_dt':.025,'interpolated_frames':0,
         'renderer_sha256':hashlib.sha256(Path(__file__).with_name('render_fields.py').read_bytes()).hexdigest()}
 confighash=hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest()
 run=frames/'run.json'
 if run.exists():assert json.loads(run.read_text())==config,'Different renderer configuration: use another output name'
 else:run.write_text(json.dumps(config,indent=2)+'\n')
 renderer=None;records=[];began=time.monotonic()
 for index in range(args.count):
  info=args.states/f'state_{index:04d}.json';raw=info.with_suffix('.raw')
  deadline=time.monotonic()+1800
  while not info.exists():
   if time.monotonic()>deadline:raise TimeoutError(f'Checkpoint {index} not published')
   time.sleep(.5)
  meta=json.loads(info.read_text());assert abs(meta['time']-index*.025)<1e-8
  recordpath=frames/f'frame{index:06d}.json';png=recordpath.with_suffix('.png')
  if recordpath.exists() and png.exists():
   record=json.loads(recordpath.read_text());assert record['config_sha256']==confighash
   records.append(record);continue
  nx,ny,nz=meta['dimensions_xyz'];blob=raw.read_bytes();assert len(blob)==nx*ny*nz*32
  U=np.frombuffer(blob,dtype='<f4').reshape(nz,ny,nx,8)
  assert np.isfinite(U).all(),'Nonfinite fluid state'
  bounds=np.array(meta['bounds']);cell=(bounds[:,1]-bounds[:,0])/np.array([nx,ny,nz])
  if renderer is None:
   renderer=Renderer(args.width,args.height,bounds[:,0],bounds[:,1],args.eye,args.target,float(cell.min())*.4,.8)
  volume,stats=shade(U,cell,gamma=meta['gamma'],soot_gain=args.soot,emission_gain=args.emission)
  im=renderer.draw(volume)
  temp=png.with_suffix('.tmp');im.save(temp,format='PNG',compress_level=1);os.replace(temp,png)
  record={'index':index,'video_time':index/args.fps,'simulation_time':meta['time'],
          'state_sha256':hashlib.sha256(blob).hexdigest(),'pixel_sha256':hashlib.sha256(im.tobytes()).hexdigest(),
          'config_sha256':confighash,'all_finite':True,'field_stats':stats,'mean_rgb':np.array(im).mean(axis=(0,1)).tolist()}
  recordpath.write_text(json.dumps(record,indent=2)+'\n');records.append(record)
  if index%12==0 or index==args.count-1:print(json.dumps({'frames':index+1,'total':args.count,'sim_t':meta['time'],'elapsed':time.monotonic()-began}),flush=True)
 command=['ffmpeg','-hide_banner','-loglevel','error','-y','-framerate',str(args.fps),'-i',str(frames/'frame%06d.png'),'-frames:v',str(args.count),'-c:v','libx264','-threads','1','-preset','medium','-crf','16','-pix_fmt','yuv420p','-movflags','+faststart',str(args.output)]
 subprocess.run(command,check=True)
 unique=len({x['pixel_sha256'] for x in records});assert unique==args.count
 report={'config':config,'unique_frames':unique,'unique_states':len({x['state_sha256'] for x in records}),
         'actual_evolved_states':True,'all_finite':True,'frames':records}
 args.output.with_suffix('.json').write_text(json.dumps(report,indent=2)+'\n')
 sheet=Image.new('RGB',(1280,744));draw=ImageDraw.Draw(sheet)
 for i,index in enumerate([12,36,60,96,132,180]):
  im=Image.open(frames/f'frame{index:06d}.png');im.thumbnail((426,240))
  x=(i%3)*426;y=(i//3)*372;sheet.paste(im,(x,y))
  draw.text((x+8,y+245),f'Video {index/args.fps:.2f}s / simulation {records[index]["simulation_time"]:.3f}',fill='white')
 sheet=sheet.crop((0,0,1280,632));sheet.save(args.output.with_name(args.output.stem+'-contact.jpg'),quality=94)
 print(json.dumps({'complete':str(args.output),'unique_frames':unique,'elapsed':time.monotonic()-began}),flush=True)
if __name__=='__main__':main()
