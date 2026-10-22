"""Meaningful numerical checks for pressure causality and finite-volume budgets."""
from pathlib import Path
import argparse
import json
import numpy as np
import fields
from run import run

ROOT=Path(__file__).resolve().parent
OUT=ROOT/"validation"


def main(initial=None,output=None,threads=4,extra=()):
    global OUT
    if output is not None:
        OUT=Path(output)
    OUT.mkdir(parents=True,exist_ok=True)
    initial=Path(initial) if initial is not None else ROOT/"checkpoints"/"initial"
    if not initial.with_suffix(".raw").exists():
        fields.initialize(initial)
    on=run(initial,OUT/"pressure_on",end=.5,output_dt=.5,threads=threads,
           extra=[*extra,"--gravity","0"],convert=False)[-1]
    off=run(initial,OUT/"pressure_off",end=.5,output_dt=.5,threads=threads,
            extra=[*extra,"--gravity","0","--pressure-off"],convert=False)[-1]
    u,meta=fields.load(initial)
    rest=np.zeros((12,14,12,8),np.float32)
    rest[...,0]=1
    rest[...,4]=1/(meta["gamma"]-1)
    rest[...,6]=.23
    restmeta=dict(meta,dimensions_xyz=[12,14,12])
    fields.save(OUT/"rest",rest,restmeta)
    static=run(OUT/"rest",OUT/"rest_run",end=.5,output_dt=.5,threads=threads,
               extra=["--no-sources"],convert=False)[-1]
    rest_after,_=fields.load(OUT/"rest_run"/"state_0001")
    initial_radius=on["initial_totals"]
    checks={
        "pressure_on_kinetic_energy":on["kinetic_energy"],
        "pressure_off_kinetic_energy":off["kinetic_energy"],
        "pressure_on_radial_momentum":on["radial_momentum_r4"],
        "pressure_off_radial_momentum":off["radial_momentum_r4"],
        "pressure_on_material_rms_radius":on["material_rms_radius"],
        "pressure_off_material_rms_radius":off["material_rms_radius"],
        "pressure_off_meaning":"Causal ablation only: constant ambient momentum/energy flux pressure; chemistry/internal energy still evolve; gravity zero for both cases.",
        "uniform_rest_max_abs_change":float(np.max(np.abs(rest_after-rest))),
        "on_mass_relative_budget_error":abs(on["conservation_residual"][0])/on["initial_totals"][0],
        "on_total_energy_relative_budget_error":abs(on["conservation_residual"][4])/on["initial_totals"][4],
        "on_mass_absolute_budget_error":on["conservation_residual"][0],
        "on_total_energy_absolute_budget_error":on["conservation_residual"][4],
        "on_min_density":on["rho_min"],"on_min_pressure":on["pressure_min"],
        "on_max_cfl":on["max_cfl"],"on_rejected_steps":on["rejected_steps"],
    }
    assert checks["uniform_rest_max_abs_change"] < 1e-6
    assert checks["pressure_on_kinetic_energy"] > 1
    assert checks["pressure_on_radial_momentum"] > 1
    assert checks["pressure_off_kinetic_energy"] < 1e-12
    assert checks["pressure_off_radial_momentum"] < 1e-10
    assert checks["pressure_on_material_rms_radius"] > 1.2*checks["pressure_off_material_rms_radius"]
    assert checks["on_mass_relative_budget_error"] < 1e-6
    assert checks["on_total_energy_relative_budget_error"] < 1e-6
    assert checks["on_min_density"] > 0 and checks["on_min_pressure"] > 0
    checks["passed"]=True
    (OUT/"checks.json").write_text(json.dumps(checks,indent=2)+"\n")
    print(json.dumps(checks,indent=2))


if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--initial")
    ap.add_argument("--output")
    ap.add_argument("--threads",type=int,default=4)
    args,extra=ap.parse_known_args()
    main(args.initial,args.output,args.threads,extra)
