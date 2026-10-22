#!/usr/bin/env python3
"""Compare empty-brick acceleration against the ordinary cache renderer."""
import argparse,json
from pathlib import Path
import numpy as np
from cache_fast import CachedRenderer

def main():
    ap=argparse.ArgumentParser();ap.add_argument('source',type=Path);ap.add_argument('cache',type=Path);ap.add_argument('output',type=Path)
    ap.add_argument('--width',type=int,default=320);ap.add_argument('--height',type=int,default=180)
    ap.add_argument('--times',type=float,nargs='+',default=[0,8.4,9.96]);a=ap.parse_args()
    cfg=json.loads(a.cache.with_suffix('.json').read_text())['configuration']
    r=CachedRenderer(a.source.read_text(),a.width,a.height,grid=cfg['grid'],cache_path=a.cache,bounds=cfg['bounds'],dtype=cfg['storage_dtype'])
    a.output.mkdir(parents=True,exist_ok=True);results=[]
    for t in a.times:
        orig,ro=r.draw_original(t);first=r.last_float.copy();orig.save(a.output/f'original-{t}.png')
        fast,rf=r.draw(t);second=r.last_float.copy();fast.save(a.output/f'fast-{t}.png')
        error=np.abs(first[:,:,:3]-second[:,:,:3]);rgb=np.abs(np.asarray(orig).astype(int)-np.asarray(fast).astype(int))
        item={'time':t,'original_seconds':ro['render_seconds'],'fast_seconds':rf['render_seconds'],'speedup':ro['render_seconds']/rf['render_seconds'],'mean_abs_float_error':float(error.mean()),'max_abs_float_error':float(error.max()),'p99_abs_float_error':float(np.percentile(error,99)),'mean_abs_rgb8_error':float(rgb.mean()),'max_abs_rgb8_error':int(rgb.max()),'rgb8_fraction_changed':float((rgb!=0).mean()),'source_sha256':cfg['source_sha256']}
        results.append(item);print(json.dumps(item),flush=True)
    (a.output/'audit.json').write_text(json.dumps(results,indent=2)+'\n')
if __name__=='__main__':main()
