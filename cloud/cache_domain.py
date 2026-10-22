#!/usr/bin/env python3
"""Analytic cache-boundary proof for the selected ten-second 16:9 flight.

This proof bounds every primary midpoint and source sun probe. It also uses
an infinite positive-octave tail bound to prove that cached/exact switches at
the vertical faces lie in empty space. It is deliberately source-specific;
changed geometry or camera code must not inherit this report without review.
"""
import argparse,hashlib,json,math,re
from pathlib import Path

def prove(source):
    normalized=re.sub(r'\s+','',source)
    required=[
      '1.2-length(vec3(mod(p.xz,16.0)-8.0,p.y*.64))*.25',
      'floata=.8;', 'floatv=1.0;', 'd+=a*(.6-v);','a*=.45;',
      'p=vec3(3.5,7.0-u_time/5.0,u_time)-r/64.0;',
      'float(i)<2e3&&t>.005','p+=r/32.0;',
      'for(intj=0;j<64;j++)s+=g(p+vec3(-2.0,3.0,-1.0)*(float(j)+.5)/48.0,4.);'
    ]
    missing=[s for s in required if s not in normalized]
    if missing:raise ValueError('Source no longer matches this proof: '+repr(missing))
    horizon=10.;count=2000;step=1/32
    last=(count-.5)*step
    aspect=16/9
    rx=(aspect/2)/math.sqrt(1+(aspect/2)**2)
    ry=.5/math.sqrt(1.25)
    rzmin=1/math.sqrt(1+(aspect/2)**2+.25)
    primary=[ [3.5-last*rx,5-last*ry,step*.5*rzmin],
              [3.5+last*rx,7+last*ry,horizon+last] ]
    sunlo=[-2*63.5/48,3*.5/48,-63.5/48]
    sunhi=[-2*.5/48,3*63.5/48,-.5/48]
    shadow=[[v+d for v,d in zip(primary[0],sunlo)],
            [v+d for v,d in zip(primary[1],sunhi)]]
    support=(1.2+.8*.6/(1-.45))/.16
    bounds=[[-42.,-14.,-2.],[48.,14.,74.]]
    grid=[1024,384,896]
    voxel=[(hi-lo)/n for lo,hi,n in zip(*bounds,grid)]
    inner=[[lo+h/2 for lo,h in zip(bounds[0],voxel)],
           [hi-h/2 for hi,h in zip(bounds[1],voxel)]]
    for ax in [0,2]:
        assert inner[0][ax]<primary[0][ax]<primary[1][ax]<inner[1][ax]
        assert inner[0][ax]<shadow[0][ax]<shadow[1][ax]<inner[1][ax]
    assert inner[0][1]<-support<support<inner[1][1]
    result=dict(
      source_sha256=hashlib.sha256(source.encode()).hexdigest(),
      scope='Any 16:9 pixel grid, time 0 through 10 seconds inclusive',
      pixel_centers='Continuous screen rectangle bound, conservative for all finite resolutions',
      ray_samples=count,ray_step=step,last_midpoint_distance=last,
      primary_query_bounds=primary,shadow_query_bounds=shadow,
      density_support_y=[-support,support],
      support_proof='v is capped into [0,1]; each octave adds at most .6*a. Infinite sum is .8*.6/(1-.45). Envelope <=1.2-.16*abs(y). Thus density is zero when abs(y)>=(1.2+.8*.6/(1-.45))/.16.',
      bounds=bounds,grid=grid,voxel_size=voxel,inner_interpolation_bounds=inner,
      cache_storage='f2',cache_bytes=math.prod(grid)*4,
      proof='All primary and shadow probes are within the inner cache in x/z. Any y probe outside the inner cache is in identically zero density, with over one world unit of empty margin. Consequently no cached/exact transition intersects nonzero cloud density in this ten-second clip.',
      cache_boundary_visible_transition=False,
      recommended_workers=2,
      numerical_roundoff_allowance='All relevant x margins exceed 1 world unit and the smallest z margin exceeds .6 world units, far above float accumulation roundoff.'
    )
    return result

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('source',type=Path);ap.add_argument('output',type=Path);a=ap.parse_args()
    r=prove(a.source.read_text());a.output.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r))
