#!/usr/bin/env python3
"""Optional conservative empty-brick acceleration of the offline field cache.

This never changes source density, illumination or fixed sample indices.
Skipping repeated empty additions changes only floating-point accumulation
roundoff; validation compares this backend against the original cache renderer.
"""
import argparse,hashlib,json,os,time
from pathlib import Path
import numpy as np
from scipy.ndimage import maximum_filter
import cache_volume as base
Image,ImageDraw=base.Image,base.ImageDraw

class CachedRenderer(base.CachedRenderer):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        cache_path=kwargs.get('cache_path',args[4] if len(args)>4 else None)
        if cache_path is None:raise ValueError('Fast renderer requires saved cache')
        if self.config["density_sha256"] != "dc77dce9776e1e7bca41d92f4c371c5ac724d7f3692099ac6b946b2d331cd948":
            raise ValueError("The vertical support proof applies only to the selected density source")
        self.base_program,self.base_vao=self.program,self.vao
        self.build_occupancy(Path(cache_path))
        density,runtime,cfg=base.config_from_source(self.source,self.config['bounds'])
        marker='p+=r/32.0;'
        if runtime.count(marker)!=1 or 'float(i)<2e3' not in runtime:
            raise ValueError('Fast path only supports selected 2000 midpoint source')
        runtime=runtime.replace(marker,'''if(abs(p.y)>13.&&p.y*r.y>=0.)break;
 int skip=min(emptySamples(p+r/32.,r),1999-i);
 if(skip>0){p+=r*(float(skip)/32.);i+=skip;}
 p+=r/32.0;''')
        self.program=self.ctx.program(vertex_shader=base.VERTEX,fragment_shader=base.PREFIX+density+self.lookup_glsl()+self.occupancy_glsl()+runtime)
        self.program['u_volume'].value=0;self.program['u_occupancy'].value=1
        self.program['u_resolution'].value=(self.width,self.height)
        self.vao=self.ctx.vertex_array(self.program,[(self.vbo,'2f','position')])
        self.config['acceleration']='Conservative 16-voxel bricks with 1-voxel trilinear halo; exact source indices retained; grouped empty additions introduce only floating-point roundoff'

    def build_occupancy(self,path):
        start=time.monotonic();nx,ny,nz=self.grid;b=16
        if any(n%b for n in self.grid):raise ValueError('Fast grid dimensions must divide by16')
        key_fields={k:self.config[k] for k in ['density_sha256','view_octaves','algorithm_version','grid','bounds','storage_dtype']}
        key_fields.update(occupancy_algorithm=1,brick_size=b,halo_voxels=1,cache_size=path.stat().st_size,cache_mtime_ns=path.stat().st_mtime_ns)
        key=hashlib.sha256(json.dumps(key_fields,sort_keys=True).encode()).hexdigest()
        occpath=path.with_name(path.name+'.occupancy.npy');metapath=path.with_name(path.name+'.occupancy.json')
        occ=None
        if occpath.is_file() and metapath.is_file():
            meta=json.loads(metapath.read_text())
            if meta.get('key')==key:
                candidate=np.load(occpath,allow_pickle=False)
                if (candidate.shape==(nz//b,ny//b,nx//b) and candidate.dtype==np.dtype('u1')
                    and np.isin(candidate,[0,255]).all()
                    and hashlib.sha256(candidate.tobytes()).hexdigest()==meta.get('sha256')):
                    occ=candidate
        if occ is None:
            data=np.memmap(path,dtype=self.dtype,mode='r',shape=(nz,ny,nx,2))
            occ=np.empty((nz//b,ny//b,nx//b),dtype='u1')
            for z in range(nz//b):
                z0=max(0,z*b-1);z1=min(nz,(z+1)*b+1)
                plane=np.any(data[z0:z1,:,:,0]>0,axis=0)
                plane=maximum_filter(plane,size=3,mode='constant',cval=0)
                occ[z]=plane.reshape(ny//b,b,nx//b,b).max(axis=(1,3))*255
            temporary=occpath.with_name(occpath.name+f'.{os.getpid()}.part')
            with temporary.open('wb') as handle:np.save(handle,occ)
            os.replace(temporary,occpath)
            meta={'key':key,'configuration':key_fields,'shape':list(occ.shape),'occupied_fraction':float((occ>0).mean()),'sha256':hashlib.sha256(occ.tobytes()).hexdigest()}
            temporary=metapath.with_name(metapath.name+f'.{os.getpid()}.part')
            temporary.write_text(json.dumps(meta,indent=2)+'\n')
            os.replace(temporary,metapath)
        self.occ_grid=(nx//b,ny//b,nz//b)
        self.occupancy=self.ctx.texture3d(self.occ_grid,1,occ.tobytes(),dtype='f1')
        self.occupancy.filter=(base.moderngl.NEAREST,base.moderngl.NEAREST)
        self.occupancy.repeat_x=self.occupancy.repeat_y=self.occupancy.repeat_z=False
        self.occupancy.use(1)
        self.report({'stage':'occupancy','seconds':time.monotonic()-start,'occupied_fraction':float((occ>0).mean()),'bricks':int(occ.size)})

    def occupancy_glsl(self):
        lo,hi=self.config['bounds'];span=[h-l for l,h in zip(lo,hi)]
        brick=[s/n for s,n in zip(span,self.occ_grid)]
        return f'''
uniform sampler3D u_occupancy;
int emptySamples(vec3 p,vec3 r){{
 vec3 q=(p-{base.vec3(lo)})/{base.vec3(brick)};
 ivec3 cell=ivec3(floor(q));
 if(any(lessThan(cell,ivec3(0)))||any(greaterThanEqual(cell,ivec3{self.occ_grid})))return 0;
 if(texelFetch(u_occupancy,cell,0).r>0.)return 0;
 vec3 side=mix(fract(q),1.-fract(q),step(vec3(0),r))*{base.vec3(brick)};
 vec3 distance=side/max(abs(r),vec3(1e-9));
 return max(0,int(floor(min(distance.x,min(distance.y,distance.z))*32.))-1);
}}
'''

    def draw(self,t,direct=False):
        self.occupancy.use(1)
        image,record=super().draw(t,direct=direct)
        if not direct:
            record['renderer_kind']='offline_interpolated_field_empty_bricks'
            record['empty_space_acceleration']=self.config['acceleration']
        return image,record

    def draw_original(self,t):
        prog,vao=self.program,self.vao
        self.program,self.vao=self.base_program,self.base_vao
        try:return super().draw(t)
        finally:self.program,self.vao=prog,vao

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('source',type=Path);ap.add_argument('output',type=Path)
    ap.add_argument('--grid',type=int,nargs='+',default=[128],help='One cubic size or X Y Z sizes')
    ap.add_argument('--bounds',type=float,nargs=6,default=[v for row in base.BOUNDS for v in row],metavar=('XMIN','YMIN','ZMIN','XMAX','YMAX','ZMAX'))
    ap.add_argument('--dtype',choices=['f2','f4'],default='f4')
    ap.add_argument('--width',type=int,default=320);ap.add_argument('--height',type=int,default=180)
    ap.add_argument('--times',type=float,nargs='+',default=[0])
    ap.add_argument('--count',type=int);ap.add_argument('--fps',type=float,default=24)
    ap.add_argument('--start',type=int,default=0);ap.add_argument('--stride',type=int,default=1)
    ap.add_argument('--cache',type=Path);ap.add_argument('--audit',action='store_true')
    ap.add_argument('--reference',type=Path,nargs='*',default=[],
                    help='Prior audit directories with exact float arrays to reuse')
    args=ap.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    r=CachedRenderer(args.source.read_text(),args.width,args.height,args.grid,args.cache,bounds=args.bounds,dtype=args.dtype)
    references={}
    for directory in args.reference:
        for audit_path in directory.glob('cache-audit-*.json'):
            prior=json.loads(audit_path.read_text())
            for n,entry in enumerate(prior.get('audits',[])):
                direct=entry['direct']
                array_path=directory/f'exact{entry["cached"]["index"]:06d}.npy'
                if direct['source_sha256']==r.config['source_sha256'] and array_path.is_file():
                    references[direct['time']]=(array_path,direct)
    indices=range(args.start,args.count,args.stride) if args.count is not None else range(len(args.times))
    records=[];audits=[]
    for i in indices:
        t=i/args.fps if args.count is not None else args.times[i]
        target=args.output/f'frame{i:06d}.png'
        target_meta=target.with_suffix('.json')
        if not args.audit and target.is_file() and target_meta.is_file():
            old=json.loads(target_meta.read_text())
            expected={'source_sha256':r.config['source_sha256'],'width':args.width,
                      'height':args.height,'storage_dtype':r.dtype,'grid':list(r.grid),'bounds':json.loads(json.dumps(r.config['bounds'])),'time':t,
                      'renderer_kind':'offline_interpolated_field_empty_bricks'}
            intact=False
            if all(old.get(k)==v for k,v in expected.items()):
                try:
                    with Image.open(target) as previous:
                        intact=(previous.size==(args.width,args.height) and
                          hashlib.sha256(previous.convert('RGB').tobytes()).hexdigest()==old['pixel_sha256'])
                except (OSError,ValueError):
                    intact=False
            if intact:
                records.append(old)
                continue
        im,record=r.draw(t)
        temporary=target.with_name(target.name+'.part')
        im.save(temporary,format='PNG',compress_level=1)
        with Image.open(temporary) as verified:
            if hashlib.sha256(verified.convert('RGB').tobytes()).hexdigest()!=record['pixel_sha256']:
                raise RuntimeError('PNG write did not preserve the rendered pixels')
        os.replace(temporary,target)
        record.update(index=i,width=args.width,height=args.height,renderer=r.ctx.info['GL_RENDERER'])
        (args.output/f'frame{i:06d}.json').write_text(json.dumps(record,indent=2)+'\n')
        records.append(record);r.report(record)
        if args.audit:
            approximate=r.last_float.copy()
            reference_reused=False
            if t in references:
                array_path,exact_record=references[t]
                exact=np.load(array_path,allow_pickle=False)
                if exact.shape!=(args.height,args.width,4):
                    raise ValueError('Reference float array dimensions do not match')
                if hashlib.sha256(exact.tobytes()).hexdigest()!=exact_record['float_sha256']:
                    raise ValueError('Reference float array hash does not match')
                exact_image=Image.fromarray(np.rint(np.clip(exact[:,:,:3],0,1)*255).astype('uint8'))
                reference_reused=True
            else:
                exact_image,exact_record=r.draw(t,direct=True)
                exact=r.last_float
            exact_image.save(args.output/f'exact{i:06d}.png',compress_level=1)
            np.save(args.output/f'exact{i:06d}.npy',exact)
            np.save(args.output/f'cached{i:06d}.npy',approximate)
            error=np.abs(exact[:,:,:3]-approximate[:,:,:3])
            mse=float(np.mean((exact[:,:,:3]-approximate[:,:,:3])**2,dtype='f8'))
            audit=dict(time=t,all_finite=True,exact_reference_reused=reference_reused,
                       mean_absolute_rgb_error=float(error.mean()),
                       max_absolute_rgb_error=float(error.max()),
                       percentile_absolute_rgb_error={str(p):float(np.percentile(error,p)) for p in [50,90,95,99,99.9]},
                       mse=mse,psnr_db=float(-10*np.log10(mse)) if mse else None,
                       direct=exact_record,cached=record,
                       frame_speedup=exact_record['render_seconds']/record['render_seconds'])
            audits.append(audit);r.report(dict(stage='audit',**audit))
            error_image=Image.fromarray(np.rint(np.clip(error*10,0,1)*255).astype('uint8'))
            error_image.save(args.output/f'error10x{i:06d}.png')
            sheet=Image.new('RGB',(args.width*3,args.height+24),(15,18,24))
            sheet.paste(exact_image,(0,0));sheet.paste(im,(args.width,0));sheet.paste(error_image,(args.width*2,0))
            draw=ImageDraw.Draw(sheet)
            for x,label in [(0,'Exact procedural'),(args.width,f'{r.grid} offline cache'),(args.width*2,'Absolute RGB error x10')]:
                draw.text((x+6,args.height+4),label,fill='white')
            sheet.save(args.output/f'compare{i:06d}.jpg',quality=95)
    report=dict(configuration=r.config,setup=r.setup_record,renderer=r.ctx.info['GL_RENDERER'],frames=records,audits=audits,
                approximation=f'World-space trilinear interpolation of density; light cache integrates trilinear {r.config["shadow_octaves"]:g}-octave density and stores density-weighted transmittance; outside-cache probes evaluate source density and light exactly; conservative empty-brick skipping retains all source indices and haze values, with only grouped-addition float roundoff; no frame interpolation or image upscaling')
    (args.output/f'cache-audit-{args.start}.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':
    main()
