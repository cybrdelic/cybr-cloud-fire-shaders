"""Report transported soot, hot pockets, vorticity and domain occupancy."""
import argparse
import json
from pathlib import Path
import numpy as np
import fields


def analyze(stem):
    u,m=fields.load(stem)
    rho=u[...,0].astype(np.float64)
    v=u[...,1:4]/rho[...,None]
    p=(m["gamma"]-1)*(u[...,4]-.5*rho*np.sum(v*v,axis=-1))
    t=p/rho
    soot=u[...,7].astype(np.float64)
    nx,ny,nz=m["dimensions_xyz"]
    dx,dy,dz=[(b-a)/n for (a,b),n in zip(m["bounds"],[nx,ny,nz])]
    dv=dx*dy*dz
    wx=np.gradient(v[...,2],dy,axis=1)-np.gradient(v[...,1],dz,axis=0)
    wy=np.gradient(v[...,0],dz,axis=0)-np.gradient(v[...,2],dx,axis=2)
    wz=np.gradient(v[...,1],dx,axis=2)-np.gradient(v[...,0],dy,axis=1)
    curl=np.sqrt(wx*wx+wy*wy+wz*wz)
    inside=soot>.01*soot.max()
    z,y,x=np.nonzero(inside)
    boundary=np.zeros(soot.shape,bool)
    boundary[:2]=True;boundary[-2:]=True;boundary[:,:2]=True;boundary[:,-2:]=True;boundary[:,:,:2]=True;boundary[:,:,-2:]=True
    result=dict(time=m["time"],soot_mass=float(soot.sum()*dv),
        fuel_mass=float(u[...,5].sum(dtype=np.float64)*dv),
        soot_peak_density=float(soot.max()),
        soot_weighted_temperature=float(np.sum(soot*t)/soot.sum()),
        soot_weighted_vorticity=float(np.sum(soot*curl)/soot.sum()),
        vorticity_max=float(curl.max()),
        soot_mass_above_temperature_3=float(soot[t>=3].sum()*dv),
        soot_mass_above_temperature_6=float(soot[t>=6].sum()*dv),
        soot_mass_boundary_fraction=float(soot[boundary].sum()/soot.sum()),
        soot_extent_1pct_peak=[[float(m["bounds"][0][0]+x.min()*dx),float(m["bounds"][0][0]+(x.max()+1)*dx)],
                              [float(m["bounds"][1][0]+y.min()*dy),float(m["bounds"][1][0]+(y.max()+1)*dy)],
                              [float(m["bounds"][2][0]+z.min()*dz),float(m["bounds"][2][0]+(z.max()+1)*dz)]])
    return result


if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument("stems",nargs="+")
    args=ap.parse_args()
    results=[dict(path=str(Path(s).resolve()),**analyze(s)) for s in args.stems]
    print(json.dumps(results,indent=2))
