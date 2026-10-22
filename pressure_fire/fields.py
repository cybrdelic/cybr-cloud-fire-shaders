"""Initialize/load conservative reactive Euler volumes (C-contiguous z,y,x,8)."""
from pathlib import Path
import argparse
import json
import numpy as np

ROOT = Path(__file__).resolve().parent
PARAMS = dict(gamma=1.3, ambient_pressure=1.0, ambient_rho=1.0,
              ambient_temperature=1.0, ignition_temperature=1.30,
              fully_active_temperature=2.0, heat_release=65.0,
              reaction_rate=2.0, oxygen_ratio=3.0, soot_yield=0.16,
              cooling_time=4.0, buoyancy=0.10, cfl=0.35, vorticity_confinement=0.,
              bounds=[[-6., 6.], [-1., 13.], [-6., 6.]],
              order="C contiguous [z,y,x,channel]", units="nondimensional",
              channels=["rho", "mx", "my", "mz", "E", "fuel", "oxygen", "soot"])


def save(stem, u, meta, compressed=False):
    stem = Path(stem)
    stem.parent.mkdir(parents=True, exist_ok=True)
    np.asarray(u, dtype="<f4", order="C").tofile(stem.with_suffix(".raw"))
    stem.with_suffix(".json").write_text(json.dumps(meta, indent=2) + "\n")
    if compressed:
        export_npz(stem, u, meta)


def load(stem):
    stem = Path(stem).with_suffix("")
    meta = json.loads(stem.with_suffix(".json").read_text())
    nx, ny, nz = meta["dimensions_xyz"]
    u = np.fromfile(stem.with_suffix(".raw"), dtype="<f4").reshape(nz, ny, nx, 8)
    return u, meta


def export_npz(stem, u=None, meta=None):
    stem = Path(stem).with_suffix("")
    if u is None:
        u, meta = load(stem)
    rho = u[..., 0]
    velocity = u[..., 1:4] / rho[..., None]
    internal_energy = u[..., 4] - .5 * rho * np.sum(velocity**2, axis=-1)
    pressure = (meta["gamma"] - 1) * internal_energy
    temperature = pressure / rho
    np.savez_compressed(stem.with_suffix(".npz"), U=u, rho=rho,
                        velocity=velocity, pressure=pressure,
                        temperature=temperature, internal_energy=internal_energy,
                        fuel=u[..., 5], oxygen=u[..., 6], soot=u[..., 7],
                        bounds=np.asarray(meta["bounds"]), time=meta["time"],
                        gamma=meta["gamma"], metadata=json.dumps(meta))


def initialize(stem, shape=(48, 56, 48), profile="baseline"):
    nx, ny, nz = shape
    meta = dict(PARAMS, dimensions_xyz=list(shape), time=0.0)
    coords = [np.linspace(lo + (hi-lo)/(2*n), hi - (hi-lo)/(2*n), n)
              for (lo, hi), n in zip(meta["bounds"], shape)]
    z, y, x = np.meshgrid(coords[2], coords[1], coords[0], indexing="ij")
    # Fixed initial heterogeneity seeds baroclinic vorticity. It is never animated.
    hetero = (.23*np.sin(3.7*x + 1.2*y)*np.cos(4.2*z - .7*y)
              + .13*np.sin(8.1*z + 2.8*y)*np.cos(7.3*x - 1.5*z)
              + .08*np.sin(11.1*y + 3.3*x)*np.cos(9.1*z + 1.1*x))
    if profile=="oil":
        meta.update(profile="irregular rich oil cloud", heat_release=220.,
                    reaction_rate=3.5, cooling_time=8., buoyancy=.35, soot_yield=.22)
        # Six connected initial fuel pockets; boundaries are fixed only at t=0.
        lobes=[((0.,.93,0.),(.87,.60,.72)),
               ((-.77,1.10,.08),(.62,.44,.48)),
               ((.78,1.15,-.18),(.58,.52,.43)),
               ((.14,1.49,.39),(.49,.60,.49)),
               ((-.27,.60,-.63),(.57,.40,.48)),
               ((.48,.60,.49),(.53,.39,.41))]
        remaining=np.ones_like(x)
        for (cx,cy,cz),(rx,ry,rz) in lobes:
            radius2=((x-cx)/rx)**2+((y-cy)/ry)**2+((z-cz)/rz)**2
            pocket=1/(1+np.exp(np.clip(9*(radius2-1-.65*hetero),-80,80)))
            remaining*=1-pocket
        envelope=1-remaining
        mixture=np.clip(envelope*(.84+.35*hetero),0.,1.)
        rho=1+.40*mixture
        fuel_fraction=np.clip(.34*mixture*(1+.55*hetero),0.,.49)
        oxygen_fraction=.23*(1-fuel_fraction)
        # Local ignition energies, deposited once into an asymmetric connected region.
        seed2=((x-.08)/.32)**2+((y-.72)/.28)**2+((z+.12)/.25)**2
        seed3=((x+.31)/.24)**2+((y-.83)/.24)**2+((z-.10)/.27)**2
        pressure=1+.75*mixture+18*np.exp(-seed2**2)+9*np.exp(-seed3**2)
    else:
        r2 = (x/1.22)**2 + ((y-1.0)/.88)**2 + (z/1.06)**2
        envelope = 1/(1+np.exp(np.clip((r2 - 1.0 - .22*hetero)*7., -80, 80)))
        mixture = np.clip(envelope*(.82 + hetero), 0., 1.)
        rho = 1 + .28*mixture
        fuel_fraction = .20*mixture
        oxygen_fraction = .23*(1-fuel_fraction)
        seed2 = ((x-.12)/.40)**2 + ((y-.87)/.33)**2 + ((z+.08)/.36)**2
        seed = np.exp(-seed2**2)
        pressure = 1 + 3.2*mixture + 6.0*seed
    u = np.zeros((nz, ny, nx, 8), np.float32)
    u[..., 0] = rho
    u[..., 4] = pressure/(meta["gamma"] - 1)
    u[..., 5] = rho*fuel_fraction
    u[..., 6] = rho*oxygen_fraction
    u[..., 7] = rho*.0015*mixture
    save(stem, u, meta, compressed=True)
    print(json.dumps(dict(stem=str(Path(stem).resolve()), shape=u.shape,
                          temperature_range=[float((pressure/rho).min()), float((pressure/rho).max())],
                          pressure_range=[float(pressure.min()), float(pressure.max())])))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["init", "convert"])
    ap.add_argument("stem")
    ap.add_argument("--shape", nargs=3, type=int, default=[48, 56, 48])
    ap.add_argument("--profile", choices=["baseline","oil"],default="baseline")
    args = ap.parse_args()
    initialize(args.stem, tuple(args.shape), args.profile) if args.mode == "init" else export_npz(args.stem)
