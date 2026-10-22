"""Run the CPU Euler reference and write field metadata/NPZ checkpoints."""
from pathlib import Path
import argparse
import json
import os
import subprocess
import fields

ROOT = Path(__file__).resolve().parent

def run(initial, output, end=.5, output_dt=.125, threads=8, extra=(), convert=True):
    initial, output = Path(initial).with_suffix(""), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    _, meta = fields.load(initial)
    nx, ny, nz = meta["dimensions_xyz"]
    spacing = [(b[1]-b[0])/n for b, n in zip(meta["bounds"], [nx,ny,nz])]
    from build_native import build
    exe = build()
    param_flags={"gamma":"--gamma", "cfl":"--cfl", "buoyancy":"--gravity",
                 "cooling_time":"--cooling", "reaction_rate":"--rate", "heat_release":"--heat",
                 "ignition_temperature":"--ignition", "fully_active_temperature":"--active",
                 "oxygen_ratio":"--oxygen-ratio", "soot_yield":"--soot-yield",
                 "vorticity_confinement":"--confinement"}
    parameters=[]
    for key,flag in param_flags.items():
        parameters += [flag,str(meta.get(key,0.))]
        if flag in extra:
            meta[key]=float(extra[list(extra).index(flag)+1])
    cmd = [str(exe), "--input", str(initial.with_suffix(".raw")), "--output", str(output),
           "--shape", *map(str, [nx,ny,nz]), "--spacing", *map(str, spacing),
           "--end", str(end), "--output-dt", str(output_dt), "--threads", str(threads),
           "--initial-time", str(meta["time"]), *parameters, *extra]
    (output / "command.json").write_text(json.dumps(cmd, indent=2) + "\n")
    def finish_checkpoint(d):
        stem=output/f'state_{d["index"]:04d}'
        checkpoint_meta=dict(meta, time=d["time"], diagnostics=d,
                             pressure_coupling="--pressure-off" not in extra,
                             command=cmd, output_interval=output_dt)
        partial=stem.with_suffix(".json.partial")
        partial.write_text(json.dumps(checkpoint_meta, indent=2) + "\n")
        partial.replace(stem.with_suffix(".json"))
        if convert:
            fields.export_npz(stem)
    published=set()
    env=dict(os.environ)
    env.setdefault("OMP_WAIT_POLICY","PASSIVE")
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True, bufsize=1,env=env) as proc:
        for line in proc.stdout:
            print(line, end="", flush=True)
            if line.startswith("t="):
                lines=(output/"diagnostics.jsonl").read_text().splitlines()
                for record in lines:
                    try:
                        d=json.loads(record)
                    except json.JSONDecodeError:
                        continue
                    if d["index"] not in published:
                        finish_checkpoint(d)
                        published.add(d["index"])
        if proc.wait():
            raise subprocess.CalledProcessError(proc.returncode,cmd)
    diagnostics=[json.loads(line) for line in (output/"diagnostics.jsonl").read_text().splitlines()]
    for d in diagnostics:
        stem=output/f'state_{d["index"]:04d}'
        if d["index"] not in published:
            finish_checkpoint(d)
    return diagnostics

if __name__ == "__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("initial")
    ap.add_argument("output")
    ap.add_argument("--end", type=float, default=.5)
    ap.add_argument("--output-dt", type=float, default=.125)
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--no-convert", action="store_true")
    args, extra=ap.parse_known_args()
    run(args.initial, args.output, args.end, args.output_dt, args.threads, extra, not args.no_convert)
