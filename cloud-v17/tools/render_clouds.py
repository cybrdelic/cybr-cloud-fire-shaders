#!/usr/bin/env python3
"""Reproducible native-pixel cloud rendering with an explicit spatial cache.

The standalone shaders are procedural. This offline renderer evaluates those
density functions on a fixed world lattice, integrates the same sunlight path
through that lattice, and interpolates density plus density-weighted optical
depth. Every film frame has its own camera evaluation. There is no image
generation, temporal interpolation, frame reuse, or image enlargement.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import time

os.environ.setdefault("LP_NUM_THREADS", "8")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MESA_SHADER_CACHE_DIR", "/tmp/cloud-render-mesa-cache")
if Path("/tmp/cloud-render-deps").exists():
    sys.path.insert(0, "/tmp/cloud-render-deps")
import moderngl
import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import maximum_filter

ROOT = Path(__file__).resolve().parents[1]
VERTEX = """#version 330
in vec2 position;
void main(){gl_Position=vec4(position,0,1);}
"""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8*1024*1024), b""):
            value.update(block)
    return value.hexdigest()


def save_png(image, path):
    """Encode in memory before an atomic, checked write to the mounted workspace."""
    encoded = io.BytesIO()
    image.save(encoded, format="PNG", compress_level=1)
    data = encoded.getvalue()
    temporary = path.with_suffix(path.suffix + ".part")
    with temporary.open("wb") as stream:
        written = stream.write(data)
        if written != len(data):
            raise IOError(f"Incomplete PNG write: {path}")
        stream.flush()
        os.fsync(stream.fileno())
    if temporary.stat().st_size != len(data) or file_digest(temporary) != digest(data):
        raise IOError(f"PNG did not persist intact: {path}")
    temporary.replace(path)


def vector(value):
    return "vec3(" + ",".join(f"{float(v):.10f}" for v in value) + ")"


def report(**values):
    print(json.dumps(values), flush=True)


def load_config(scene):
    cfg = json.loads((ROOT / "src" / f"{scene}-render.json").read_text())
    source_path = ROOT / "src" / cfg["source"]
    cfg["source_sha256"] = digest(source_path.read_bytes())
    cfg["scene"] = scene
    return cfg, source_path.read_text()


class Engine:
    def __init__(self, cfg, source):
        self.cfg = cfg
        self.source = source
        self.ctx = moderngl.create_standalone_context(backend="egl", require=330)
        self.vbo = self.ctx.buffer(np.array([-1, -1, 3, -1, -1, 3], dtype="f4").tobytes())
        self.texture = None
        self.occupancy = None
        self.grid = None
        self.cache_hash = None
        self.last_float = None

    def program(self, fragment):
        p = self.ctx.program(vertex_shader=VERTEX, fragment_shader="#version 330\n" + fragment)
        return p, self.ctx.vertex_array(p, [(self.vbo, "2f", "position")])

    def tex3(self, grid, channels=2, data=None, nearest=False):
        tex = self.ctx.texture3d(tuple(grid), channels, data=data, dtype="f2", alignment=1)
        tex.filter = ((moderngl.NEAREST, moderngl.NEAREST) if nearest
                      else (moderngl.LINEAR, moderngl.LINEAR))
        tex.repeat_x = tex.repeat_y = tex.repeat_z = False
        return tex

    def bake(self, grid, cache):
        begin = time.monotonic()
        nx, ny, nz = map(int, grid)
        grid = (nx, ny, nz)
        if any(v % 8 for v in grid):
            raise ValueError("Cache grid must have dimensions divisible by eight")
        cache.parent.mkdir(parents=True, exist_ok=True)
        lo = np.array(self.cfg["bounds"][0], dtype=float)
        span = np.array(self.cfg["bounds"][1], dtype=float) - lo
        raw_path = cache.with_suffix(".density.bin")
        raw = np.memmap(raw_path, dtype="f2", mode="w+", shape=(nz, ny, nx, 2))
        raw_texture = self.tex3(grid, 2)
        target = self.ctx.texture((nx, ny), 2, dtype="f4")
        fbo = self.ctx.framebuffer([target])
        fbo.use()
        header = f"""
uniform int bakeLayer;
out vec2 bakeField;
vec3 bakePosition(){{return {vector(lo)}+
vec3(gl_FragCoord.xy,float(bakeLayer)+.5)*{vector(span)}/{vector(grid)};}}
"""
        p, vao = self.program(self.source + header + """
void main(){vec3 p=bakePosition();bakeField=vec2(density(p),densityShadow(p));}
""")
        for z in range(nz):
            p["bakeLayer"].value = z
            vao.render(moderngl.TRIANGLES)
            values = np.frombuffer(fbo.read(components=2, dtype="f4", alignment=1), dtype="f4").reshape(ny, nx, 2)
            if not np.isfinite(values).all() or values.min() < 0:
                raise RuntimeError(f"Invalid density layer {z}")
            raw[z] = values
            raw_texture.write(raw[z].tobytes(), viewport=(0, 0, z, nx, ny, 1), alignment=1)
            if z % max(1, nz // 12) == 0:
                report(stage="density", layer=z, layers=nz, seconds=round(time.monotonic()-begin, 2))
        raw.flush()
        density_seconds = time.monotonic()-begin
        raw_texture.use(0)
        shadow_code = f"""
uniform int bakeLayer;
uniform sampler3D rawDensity;
out vec2 bakeField;
const vec3 cacheMin={vector(lo)},cacheSpan={vector(span)};
float shadowDensity(vec3 p){{
 vec3 uv=(p-cacheMin)/cacheSpan;
 if(any(lessThan(uv,vec3(0)))||any(greaterThan(uv,vec3(1))))return 0.;
 return texture(rawDensity,uv).g;
}}
void main(){{
 vec3 uv=vec3(gl_FragCoord.xy,float(bakeLayer)+.5)/{vector(grid)};
 vec3 p=cacheMin+uv*cacheSpan;
 float rho=texture(rawDensity,uv).r;
 float tau=0.;
 if(rho>0.){{
  for(int j=0;j<{self.cfg['shadow_samples']};j++){{
   tau+=shadowDensity(p+{vector(self.cfg['shadow_step'])}*(float(j)+.5))*{self.cfg['shadow_weight']:.10f};
   if(tau>{self.cfg.get('shadow_tau_cutoff', 24.0):.10f})break;
  }}
 }}
 bakeField=vec2(rho,rho*tau);
}}
"""
        p, vao = self.program(shadow_code)
        p["rawDensity"].value = 0
        final = np.memmap(cache, dtype="f2", mode="w+", shape=(nz, ny, nx, 2))
        for z in range(nz):
            p["bakeLayer"].value = z
            vao.render(moderngl.TRIANGLES)
            values = np.frombuffer(fbo.read(components=2, dtype="f4", alignment=1), dtype="f4").reshape(ny, nx, 2)
            if not np.isfinite(values).all():
                raise RuntimeError(f"Invalid illumination layer {z}")
            final[z] = values
            if z % max(1, nz // 12) == 0:
                report(stage="sunlight", layer=z, layers=nz, seconds=round(time.monotonic()-begin, 2))
        final.flush()
        # Pad the occupied bricks by one whole brick. This safely covers the
        # trilinear interpolation support at every skipped brick boundary.
        coarse = np.asarray(raw[..., 0]).reshape(nz//8, 8, ny//8, 8, nx//8, 8).max(axis=(1, 3, 5))
        occupied = maximum_filter((coarse > 0).astype("u1"), size=3, mode="constant") > 0
        occupancy = occupied.astype("f2")
        occupancy_path = cache.with_suffix(".occupancy.bin")
        occupancy.tofile(occupancy_path)
        meta = dict(configuration=self.cfg, grid=list(grid), dtype="f2", channels=2,
                    channel_meanings=["density", "density_times_sun_optical_depth"],
                    voxel_spacing=(span/np.array(grid)).tolist(),
                    occupancy_grid=[nx//8, ny//8, nz//8],
                    occupancy_fraction=float(occupied.mean()),
                    density_fraction=float(np.count_nonzero(raw[..., 0]))/(nx*ny*nz),
                    density_seconds=density_seconds, total_bake_seconds=time.monotonic()-begin,
                    renderer=self.ctx.info["GL_RENDERER"],
                    cache_sha256=file_digest(cache),
                    approximation="Spatial trilinear density and density-weighted optical depth; standalone procedural source retained")
        cache.with_suffix(".json").write_text(json.dumps(meta, indent=2)+"\n")
        report(stage="bake_complete", **{k:meta[k] for k in ["grid", "voxel_spacing", "density_fraction", "total_bake_seconds"]})
        del raw, final
        raw_texture.release()
        target.release()
        fbo.release()
        raw_path.unlink()
        return meta

    def load_cache(self, path):
        meta = json.loads(path.with_suffix(".json").read_text())
        if meta["configuration"] != self.cfg:
            raise ValueError("Cache does not match the current source and configuration")
        self.grid = tuple(meta["grid"])
        expected = int(np.prod(self.grid))*4
        if path.stat().st_size != expected:
            raise ValueError("Cache byte count is invalid")
        self.texture = self.tex3(self.grid)
        nx, ny, nz = self.grid
        with path.open("rb") as stream:
            for z in range(nz):
                self.texture.write(stream.read(nx*ny*4), viewport=(0, 0, z, nx, ny, 1), alignment=1)
        self.brick_grid = tuple(meta["occupancy_grid"])
        self.occupancy = self.tex3(self.brick_grid, 1, path.with_suffix(".occupancy.bin").read_bytes(), nearest=True)
        self.cache_hash = meta["cache_sha256"]
        self.cache_meta = meta

    def configure_renderer(self, width, height, step=None, direct=False):
        self.width, self.height = width, height
        self.step = float(step or self.cfg["view_step"])
        lo = np.array(self.cfg["bounds"][0], dtype=float)
        span = np.array(self.cfg["bounds"][1], dtype=float) - lo
        if direct:
            if self.cfg["scene"] == "erosion":
                original = (ROOT/"src"/"erosion-flight.glsl").read_text()
                shader = re.sub(r"^\s*#version[^\n]*\n", "", original, count=1)
                shader = re.sub(r"(?m)^\s*precision\s+\w+\s+\w+\s*;\s*", "", shader)
            else:
                shader = self.source + "\nout vec4 outColor;void main(){mainImage(outColor,gl_FragCoord.xy);}\n"
        else:
            shader = self.source + f"""
uniform sampler3D volumeField,occupancyField;
out vec4 outColor;
const vec3 cacheLower={vector(lo)},cacheExtent={vector(span)},brickGrid={vector(self.brick_grid)};
vec2 cacheHit(vec3 ro,vec3 rd){{
 vec3 a=(cacheLower-ro)/rd,b=(cacheLower+cacheExtent-ro)/rd;
 vec3 nearv=min(a,b),farv=max(a,b);
 return vec2(max(max(nearv.x,nearv.y),nearv.z),min(min(farv.x,farv.y),farv.z));
}}
float nextBrick(vec3 p,vec3 rd){{
 vec3 brickSize=cacheExtent/brickGrid;
 vec3 cell=floor((p-cacheLower)/brickSize);
 vec3 boundary=cacheLower+(cell+step(vec3(0),rd))*brickSize;
 vec3 dist=(boundary-p)/rd;
 return max(0.,min(min(dist.x,dist.y),dist.z));
}}
void main(){{
 vec3 ro,rd;camera(iTime,ro,rd,gl_FragCoord.xy);
 vec3 background=sky(rd),radiance=vec3(0);
 float transmittance=1.;
 vec2 hit=cacheHit(ro,rd);
 float dt={self.step:.12f};
 float nearT=max(0.,hit.x),farT=min(hit.y,{self.cfg['max_distance']:.12f});
 float sampleIndex=ceil(nearT/dt-.5);
 float travel=(sampleIndex+.5)*dt;
 for(int k=0;k<6000;k++){{
  if(travel>farT||transmittance<{self.cfg['transmittance_cutoff']:.12f})break;
  vec3 p=ro+rd*travel,uv=(p-cacheLower)/cacheExtent;
  if(texture(occupancyField,uv).r<.5){{
   float skipDistance=nextBrick(p,rd);
   float jump=max(1.,floor(skipDistance/dt));
   sampleIndex+=jump;travel=(sampleIndex+.5)*dt;continue;
  }}
  vec2 field=texture(volumeField,uv).rg;
  float d=field.x;
  if(d>0.){{
   float opacity=1.-exp(-d*{self.cfg['extinction']:.12f}*dt);
   vec3 lit=shade(p,rd,d,field.y/max(d,1e-7));
   lit=mix(background,lit,exp(-max(0.,travel-dt*.5)*{self.cfg['aerial_coefficient']:.12f}));
   radiance+=transmittance*opacity*lit;
   transmittance*=1.-opacity;
  }}
  sampleIndex+=1.;travel=(sampleIndex+.5)*dt;
 }}
 outColor=vec4(displayTransform(radiance+transmittance*background),1.);
}}
"""
        self.p, self.vao = self.program(shader)
        self.fbo = self.ctx.simple_framebuffer((width, height), components=4, dtype="f4")
        if "iResolution" in self.p:
            self.p["iResolution"].value = (width, height)
        if not direct:
            self.p["volumeField"].value = 0
            self.p["occupancyField"].value = 1
            self.texture.use(0)
            self.occupancy.use(1)
        self.runtime_hash = digest(shader.encode())
        self.direct = direct

    def draw(self, seconds):
        begin = time.monotonic()
        self.fbo.use()
        if "iTime" in self.p:
            self.p["iTime"].value = float(seconds)
        self.vao.render(moderngl.TRIANGLES)
        value = np.frombuffer(self.fbo.read(components=4, dtype="f4", alignment=1), dtype="f4").reshape(self.height, self.width, 4)[::-1].copy()
        if not np.isfinite(value).all():
            raise RuntimeError(f"Nonfinite pixel at time {seconds}")
        self.last_float = value
        rgb = np.rint(np.clip(value[..., :3], 0, 1)*255).astype(np.uint8)
        record = dict(time=float(seconds), render_seconds=time.monotonic()-begin,
                      all_finite=True, width=self.width, height=self.height,
                      mean_rgb=value[..., :3].mean(axis=(0, 1)).tolist(),
                      pixel_sha256=digest(rgb.tobytes()), source_sha256=self.cfg["source_sha256"],
                      runtime_sha256=self.runtime_hash, cache_sha256=self.cache_hash,
                      step=self.step, direct=self.direct)
        return Image.fromarray(rgb), record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("scene", choices=["cinematic", "erosion"])
    parser.add_argument("action", choices=["bake", "render"])
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--grid", nargs=3, type=int, default=[384, 192, 640])
    parser.add_argument("--output", type=Path, default=ROOT/"previews")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=360)
    parser.add_argument("--times", nargs="+", type=float, default=[0, 2.5, 5, 7.5, 9.9583333333333])
    parser.add_argument("--count", type=int)
    parser.add_argument("--fps", type=float, default=24)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--stride", type=int, default=1)
    parser.add_argument("--step", type=float)
    parser.add_argument("--direct", action="store_true")
    args = parser.parse_args()
    cfg, source = load_config(args.scene)
    engine = Engine(cfg, source)
    if args.action == "bake":
        engine.bake(args.grid, args.cache)
        return
    if not args.direct:
        engine.load_cache(args.cache)
    engine.configure_renderer(args.width, args.height, args.step, args.direct)
    args.output.mkdir(parents=True, exist_ok=True)
    indices = range(args.start, args.count, args.stride) if args.count else range(len(args.times))
    rows = []
    for index in indices:
        t = index/args.fps if args.count else args.times[index]
        image_path = args.output/f"frame{index:06d}.png"
        record_path = image_path.with_suffix(".json")
        if image_path.exists() and record_path.exists():
            try:
                old = json.loads(record_path.read_text())
                expected = (engine.runtime_hash, engine.cache_hash, args.width, args.height, t)
                actual = (old.get("runtime_sha256"), old.get("cache_sha256"), old.get("width"), old.get("height"), old.get("time"))
                if expected == actual:
                    with Image.open(image_path) as previous:
                        intact = previous.size == (args.width, args.height) and digest(previous.convert("RGB").tobytes()) == old.get("pixel_sha256")
                    if intact:
                        rows.append(old)
                        continue
            except (OSError, ValueError):
                pass  # An interrupted or damaged saved frame is rendered again.
        im, record = engine.draw(t)
        record["index"] = index
        save_png(im, image_path)
        record_path.write_text(json.dumps(record, indent=2)+"\n")
        rows.append(record)
        report(stage="frame", **record)
    (args.output/f"sequence-{args.start}.json").write_text(json.dumps(rows, indent=2)+"\n")
    if not args.count:
        tw = min(args.width, 640)
        th = round(args.height*tw/args.width)
        sheet = Image.new("RGB", (tw*2, (th+28)*((len(rows)+1)//2)), (12, 17, 24))
        painter = ImageDraw.Draw(sheet)
        for n, row in enumerate(rows):
            im = Image.open(args.output/f"frame{row['index']:06d}.png")
            im.thumbnail((tw, th))
            x, y = n%2*tw, n//2*(th+28)
            sheet.paste(im, (x, y))
            painter.text((x+8, y+th+7), f"{row['time']:.3f} seconds", fill="white")
        sheet.save(args.output/"contact.jpg", quality=93)


if __name__ == "__main__":
    main()
