#!/usr/bin/env python3
"""Optional offline reconstruction of a source cloud density/light field.

This is explicitly approximate: the original procedural density is sampled on a
fixed world-space lattice; shadows sample the trilinearly reconstructed source
shadow density; frame rendering interpolates density and density-weighted light.
Optional f2 storage rounds density and light to float16 after evaluation; exact
source evaluation is used for any probe outside the interpolation domain.
Camera, ray steps, extinction, colors and tone mapping remain source-derived.
The standalone FragCoord source does not require these offline textures.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import time

from render import moderngl, np, Image, ImageDraw, PREFIX, VERTEX

BOUNDS = ((-9., -14., -9.), (9., 14., 9.))
ALGORITHM_VERSION = 2


def normalize_grid(grid):
    values = (grid,)*3 if isinstance(grid, int) else tuple(grid)
    if len(values) == 1:
        values = values*3
    if len(values) != 3 or any(int(n) != n or n < 2 for n in values):
        raise ValueError('Grid must contain one or three integers >= 2')
    return tuple(int(n) for n in values)


def normalize_bounds(bounds):
    values = np.asarray(bounds,dtype='f8').reshape(2,3)
    if not np.isfinite(values).all() or np.any(values[1] <= values[0]):
        raise ValueError('Bounds must be finite minima followed by larger maxima')
    return tuple(tuple(float(v) for v in row) for row in values)


def vec3(values):
    return 'vec3('+','.join(f'{float(v):.12g}' if '.' in f'{float(v):.12g}' or 'e' in f'{float(v):.12g}' else f'{float(v):.12g}.0' for v in values)+')'


def config_from_source(source, bounds=BOUNDS):
    """Retain the source field and integrator; use exact out-of-cache probes."""
    bounds = normalize_bounds(bounds)
    if source.count('void main()') != 1:
        raise ValueError('Expected one main function')
    density, main = source.split('void main()', 1)
    main = 'void main()' + main
    primary = re.search(r'g\(p,([\d.]+)\)', main)
    # The last parenthesis of the position expression closes g's argument only;
    # using a balanced scan makes source formatting and nested float(j) safe.
    loop = re.search(r'for\(int j=0;j<(\d+);j\+\+\)s\+=g\(', main)
    if not primary or not loop:
        raise ValueError('Unsupported source primary or shadow loop')
    start = loop.end()
    depth = 0
    split = None
    close = None
    for n in range(start, len(main)):
        ch = main[n]
        if ch == '(':
            depth += 1
        elif ch == ')':
            if depth == 0:
                close = n
                break
            depth -= 1
        elif ch == ',' and depth == 0:
            split = n
    if close is None or split is None or main[close+1] != ';':
        raise ValueError('Cannot parse shadow sample')
    position = main[start:split]
    shadow_octaves = float(main[split+1:close])
    attenuation = re.search(r'exp\(-s\*([\d.]+)\)', main)
    extinction = re.search(r'exp\(-g\(p,[\d.]+\)/([\d.]+)\)', main)
    if not attenuation or not extinction:
        raise ValueError('Cannot parse source optical coefficients')
    # A static world-space cache must never silently freeze a time-varying field.
    if re.search(r'\b(?:u_time|gl_FragCoord|u_resolution)\b', density):
        raise ValueError('Density must depend only on its world-space arguments')
    cfg = dict(source_sha256=hashlib.sha256(source.encode()).hexdigest(),
               density_sha256=hashlib.sha256(density.encode()).hexdigest(),
               view_octaves=float(primary.group(1)), shadow_octaves=shadow_octaves,
               shadow_samples=int(loop.group(1)), shadow_position=position,
               shadow_weight=float(attenuation.group(1)),
               extinction_denominator=float(extinction.group(1)), bounds=bounds,
               outside_cache="exact_source_density_and_lighting",
               algorithm_version=ALGORITHM_VERSION)
    # Exact same source main; only field evaluation and shadow lookup change.
    runtime = main[:loop.start()] + main[close+2:]
    runtime, count = re.subn(r'float a = exp\(-g\(p,[\d.]+\)',
                             'vec2 field = fieldAt(p);float a = exp(-field.x',
                             runtime, count=1)
    if count != 1:
        raise ValueError('Primary evaluation rewrite failed')
    runtime, count = re.subn(r'exp\(-s\*[\d.]+\)',
                             '(field.y/max(field.x,1e-20))', runtime, count=1)
    if count != 1 or 'g(' in runtime:
        raise ValueError('Field rewrite left unsupported procedural calls')
    return density, runtime, cfg


class CachedRenderer:
    def __init__(self, source, width=640, height=360, grid=128, cache_path=None,
                 progress=True, bounds=BOUNDS, dtype="f4"):
        if dtype not in ("f2","f4"):
            raise ValueError("Cache dtype must be f2 or f4")
        self.dtype = dtype
        self.voxel_bytes = 2*np.dtype(dtype).itemsize
        grid = normalize_grid(grid)
        self.width, self.height, self.grid = width, height, grid
        self.source = source
        self.density_source, runtime, self.config = config_from_source(source, bounds)
        self.config['grid'] = list(grid)
        self.config['storage_dtype'] = dtype
        self.progress = progress
        self.ctx = moderngl.create_standalone_context(backend='egl', require=330)
        self.vbo = self.ctx.buffer(np.array([-1,-1,3,-1,-1,3], dtype='f4').tobytes())
        self.fbo = self.ctx.simple_framebuffer((width,height), components=4, dtype='f4')
        self.volume = self.ctx.texture3d(grid, 2, dtype=dtype)
        self.volume.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.volume.repeat_x = self.volume.repeat_y = self.volume.repeat_z = False
        self.setup_record = {}
        if cache_path is not None:
            cache_path = Path(cache_path)
        if cache_path and cache_path.is_file() and cache_path.with_suffix('.json').is_file():
            self.load_cache(cache_path)
        else:
            self.build_cache(cache_path)
        self.program = self.ctx.program(vertex_shader=VERTEX,
                                        fragment_shader=PREFIX+self.density_source+self.lookup_glsl()+runtime)
        self.program['u_volume'].value = 0
        self.program['u_resolution'].value = (width,height)
        self.vao = self.ctx.vertex_array(self.program, [(self.vbo,'2f','position')])
        self.direct_program = None
        self.direct_vao = None
        self.last_float = None

    def report(self, record):
        if self.progress:
            print(json.dumps(record), flush=True)

    def coordinate_glsl(self):
        lower, upper = self.config['bounds']
        span = [hi-lo for lo,hi in zip(lower,upper)]
        return vec3(lower), vec3(span), vec3(self.grid)

    def lookup_glsl(self):
        lower, span, grid = self.coordinate_glsl()
        return f"""
uniform sampler3D u_volume;
vec2 exactField(vec3 p){{
 float rho=g(p,{self.config['view_octaves']});
 if(rho<=0.)return vec2(0);
 float s=0.;
 for(int j=0;j<{self.config['shadow_samples']};j++)
  s+=g({self.config['shadow_position']},{self.config['shadow_octaves']});
 return vec2(rho,rho*exp(-s*{self.config['shadow_weight']}));
}}
vec2 fieldAt(vec3 p){{
 vec3 uv=(p-{lower})/{span}, edge=.5/{grid};
 if(any(lessThan(uv,edge))||any(greaterThan(uv,1.-edge)))return exactField(p);
 return texture(u_volume,uv).rg;
}}
"""

    def load_cache(self, path):
        start = time.monotonic()
        meta = json.loads(path.with_suffix('.json').read_text())
        cached_config = meta['configuration']
        new_config = json.loads(json.dumps(self.config))
        # A pure camera/primary-integrator edit may reuse the same world field.
        # Every density and lighting input is still checked, with both source
        # hashes retained in the audit so this cannot hide a geometry change.
        field_keys = ['density_sha256','view_octaves','shadow_octaves',
                      'shadow_samples','shadow_position','shadow_weight',
                      'bounds','algorithm_version','grid','outside_cache','storage_dtype']
        if any(cached_config[k] != new_config[k] for k in field_keys):
            raise ValueError('Cached field source/configuration does not match')
        nx,ny,nz = self.grid
        expected = nx*ny*nz*self.voxel_bytes
        if path.stat().st_size != expected:
            raise ValueError('Cached field byte count does not match')
        size = nx*ny*self.voxel_bytes
        with path.open('rb') as f:
            for z in range(nz):
                self.volume.write(f.read(size), viewport=(0,0,z,nx,ny,1),alignment=1)
        self.setup_record = dict(meta['setup'], cache_loaded=True,
                                 cache_load_seconds=time.monotonic()-start,
                                 cache_bake_source_sha256=cached_config['source_sha256'])
        self.report(dict(stage='load_cache', **self.setup_record))

    def build_cache(self, cache_path):
        nx,ny,nz = self.grid
        voxels = nx*ny*nz
        lower,span,grid = self.coordinate_glsl()
        begin = time.monotonic()
        raw = self.ctx.texture3d(self.grid,2,dtype=self.dtype)
        raw.filter = (moderngl.LINEAR, moderngl.LINEAR)
        raw.repeat_x = raw.repeat_y = raw.repeat_z = False
        slice_texture = self.ctx.texture((nx,ny),2,dtype='f4')
        slice_fbo = self.ctx.framebuffer([slice_texture])
        grid_header = f'''#version 330
uniform int u_layer;
out vec2 fields;
vec3 gridPoint(){{return {lower}+
 vec3(gl_FragCoord.xy,float(u_layer)+.5)*{span}/{grid};}}
'''
        density_program = self.ctx.program(vertex_shader=VERTEX,
            fragment_shader=grid_header+self.density_source+f'''
void main(){{vec3 p=gridPoint();fields=vec2(g(p,{self.config['view_octaves']}),g(p,{self.config['shadow_octaves']}));}}
''')
        density_vao = self.ctx.vertex_array(density_program,[(self.vbo,'2f','position')])
        slice_fbo.use()
        density_nonzero = 0
        density_sum = 0.
        for z in range(nz):
            density_program['u_layer'].value = z
            density_vao.render(moderngl.TRIANGLES)
            data = slice_fbo.read(components=2,dtype='f4',alignment=1)
            array = np.frombuffer(data,dtype='f4')
            if not np.isfinite(array).all():
                raise RuntimeError('Nonfinite exact density lattice')
            density_nonzero += int(np.count_nonzero(array[::2]))
            density_sum += float(array[::2].sum(dtype='f8'))
            raw.write(array.astype(self.dtype,copy=False).tobytes(),viewport=(0,0,z,nx,ny,1),alignment=1)
            if (z+1) % max(1,nz//8) == 0:
                self.report(dict(stage='density',layer=z+1,grid=self.grid,
                                 seconds=time.monotonic()-begin))
        density_seconds = time.monotonic()-begin
        raw.use(0)
        shadow_program = self.ctx.program(vertex_shader=VERTEX,
            fragment_shader=grid_header+self.density_source+f'''
uniform sampler3D u_raw;
float shadowDensity(vec3 p){{
 vec3 uv=(p-{lower})/{span},edge=.5/{grid};
 if(any(lessThan(uv,edge))||any(greaterThan(uv,1.-edge)))return g(p,{self.config["shadow_octaves"]});
 return texture(u_raw,uv).g;
}}
void main(){{
 vec3 p=gridPoint();
 float rho=texelFetch(u_raw,ivec3(ivec2(gl_FragCoord.xy),u_layer),0).r;
 if(rho<=0.){{fields=vec2(0);return;}}
 float s=0.;
 for(int j=0;j<{self.config['shadow_samples']};j++)
  s+=shadowDensity({self.config['shadow_position']});
 fields=vec2(rho,rho*exp(-s*{self.config['shadow_weight']}));
}}
''')
        shadow_program['u_raw'].value = 0
        shadow_vao = self.ctx.vertex_array(shadow_program,[(self.vbo,'2f','position')])
        shadow_begin = time.monotonic()
        if cache_path:
            cache_path.parent.mkdir(parents=True,exist_ok=True)
        cache_temporary = cache_path.with_name(cache_path.name+'.part') if cache_path else None
        cache_file = cache_temporary.open('wb') if cache_temporary else None
        try:
            for z in range(nz):
                shadow_program['u_layer'].value = z
                shadow_vao.render(moderngl.TRIANGLES)
                data = slice_fbo.read(components=2,dtype='f4',alignment=1)
                array = np.frombuffer(data,dtype='f4')
                if not np.isfinite(array).all():
                    raise RuntimeError('Nonfinite reconstructed lighting lattice')
                stored = array.astype(self.dtype,copy=False).tobytes()
                self.volume.write(stored,viewport=(0,0,z,nx,ny,1),alignment=1)
                if cache_file:
                    cache_file.write(stored)
                if (z+1) % max(1,nz//8) == 0:
                    self.report(dict(stage='shadow',layer=z+1,grid=self.grid,
                                     seconds=time.monotonic()-shadow_begin))
        finally:
            if cache_file:
                cache_file.close()
        if cache_path:
            os.replace(cache_temporary,cache_path)
        self.setup_record = dict(cache_loaded=False, density_seconds=density_seconds,
            shadow_seconds=time.monotonic()-shadow_begin,
            total_seconds=time.monotonic()-begin, all_finite=True,
            density_nonzero_voxels=density_nonzero,
            density_nonzero_fraction=density_nonzero/voxels,
            mean_lattice_density=density_sum/voxels,
            gpu_cache_bytes=voxels*self.voxel_bytes,
            density_and_light_storage=self.dtype,
            description='Exact source density on voxel centers; trilinear shadow-density probes; trilinear density and density-weighted transmittance at render time; exact source fallback outside the cache bounds')
        if cache_path:
            cache_path.with_suffix('.json').write_text(json.dumps(
                dict(configuration=self.config,setup=self.setup_record),indent=2)+'\n')
        self.report(dict(stage='cache_complete',**self.setup_record))
        shadow_vao.release();shadow_program.release()
        density_vao.release();density_program.release()
        raw.release();slice_fbo.release();slice_texture.release()

    def draw(self,t,direct=False):
        if direct and self.direct_program is None:
            self.direct_program = self.ctx.program(vertex_shader=VERTEX,fragment_shader=PREFIX+self.source)
            self.direct_program['u_resolution'].value=(self.width,self.height)
            self.direct_vao=self.ctx.vertex_array(self.direct_program,[(self.vbo,'2f','position')])
        program = self.direct_program if direct else self.program
        vao = self.direct_vao if direct else self.vao
        self.fbo.use()
        self.volume.use(0)
        if 'u_time' in program:
            program['u_time'].value=t
        start=time.monotonic()
        vao.render(moderngl.TRIANGLES)
        a=np.frombuffer(self.fbo.read(components=4,dtype='f4',alignment=1),dtype='f4').reshape(self.height,self.width,4)[::-1].copy()
        if not np.isfinite(a).all():
            raise RuntimeError(f'Nonfinite output at {t}')
        self.last_float=a
        rgb=np.rint(np.clip(a[:,:,:3],0,1)*255).astype('uint8')
        record=dict(time=t,render_seconds=time.monotonic()-start,
                    all_finite=True,min=float(a.min()),max=float(a.max()),
                    mean_rgb=a[:,:,:3].mean(axis=(0,1)).tolist(),
                    pixel_sha256=hashlib.sha256(rgb.tobytes()).hexdigest(),
                    float_sha256=hashlib.sha256(a.tobytes()).hexdigest(),
                    renderer_kind='direct' if direct else 'offline_interpolated_field',
                    source_sha256=self.config['source_sha256'],grid=list(self.grid),bounds=self.config['bounds'],storage_dtype=self.dtype)
        return Image.fromarray(rgb),record


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('source',type=Path);ap.add_argument('output',type=Path)
    ap.add_argument('--grid',type=int,nargs='+',default=[128],help='One cubic size or X Y Z sizes')
    ap.add_argument('--bounds',type=float,nargs=6,default=[v for row in BOUNDS for v in row],metavar=('XMIN','YMIN','ZMIN','XMAX','YMAX','ZMAX'))
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
                      'renderer_kind':'offline_interpolated_field'}
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
                approximation=f'World-space trilinear interpolation of density; light cache integrates trilinear {r.config["shadow_octaves"]:g}-octave density and stores density-weighted transmittance; outside-cache probes evaluate source density and light exactly; no frame interpolation or image upscaling')
    (args.output/f'cache-audit-{args.start}.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':
    main()
