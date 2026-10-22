"""Audit a completed sequence: unique evolved states, timings and numerical budgets."""
from pathlib import Path
import argparse
import hashlib
import json
import numpy as np


def audit(directory,count=192,interval=.025):
    directory=Path(directory)
    records=[]
    hashes=[]
    maximum_mass_relative=maximum_energy_relative=0.
    last_steps=-1
    for index in range(count):
        stem=directory/f"state_{index:04d}"
        meta=json.loads(stem.with_suffix(".json").read_text())
        d=meta["diagnostics"]
        assert abs(meta["time"]-index*interval)<1e-9,(index,meta["time"])
        assert d["index"]==index
        assert d["steps"]>last_steps
        last_steps=d["steps"]
        assert d["rho_min"]>0 and d["pressure_min"]>0
        assert d["max_cfl"]<=meta["cfl"]*1.000002
        expected=32*int(np.prod(meta["dimensions_xyz"]))
        raw=stem.with_suffix(".raw").read_bytes()
        assert len(raw)==expected,(index,len(raw),expected)
        assert np.isfinite(np.frombuffer(raw,dtype="<f4")).all()
        digest=hashlib.sha256(raw).hexdigest()
        hashes.append(digest)
        maximum_mass_relative=max(maximum_mass_relative,abs(d["conservation_residual"][0])/d["initial_totals"][0])
        maximum_energy_relative=max(maximum_energy_relative,abs(d["conservation_residual"][4])/d["initial_totals"][4])
        records.append(dict(index=index,time=meta["time"],steps=d["steps"],sha256=digest))
    assert len(set(hashes))==count,"Repeated volume state"
    assert maximum_mass_relative<1e-5
    assert maximum_energy_relative<1e-5
    result=dict(passed=True,state_count=count,unique_state_hashes=len(set(hashes)),
                time_first=records[0]["time"],time_last=records[-1]["time"],interval=interval,
                finite_positive_states=True,max_mass_relative_budget_error=maximum_mass_relative,
                max_total_energy_relative_budget_error=maximum_energy_relative,
                final_steps=last_steps,states=records)
    (directory/"audit.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps({k:v for k,v in result.items() if k!="states"},indent=2))
    return result


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("directory");p.add_argument("--count",type=int,default=192)
    p.add_argument("--interval",type=float,default=.025);args=p.parse_args()
    audit(args.directory,args.count,args.interval)
