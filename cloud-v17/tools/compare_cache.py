#!/usr/bin/env python3
"""Matched native-pixel comparisons for a finished cloud volume cache.

This deliberately reports numerical differences without declaring a universal
visual-quality threshold.  Direct renders use the delivered procedural shader;
cached renders use the same camera at the same pixel centers and time.  Optional
half-step renders measure view-ray integration error in the cached field.

Example (run after production renders release their memory):
  LP_NUM_THREADS=1 python3 tools/compare_cache.py erosion \
    --cache cache/erosion-final.bin --output validation/erosion-cache \
    --width 32 --height 18 --times 0 5 9.9583333333333 --half-step
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import time

os.environ.setdefault("LP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import numpy as np
from PIL import Image

from render_clouds import Engine, ROOT, digest, load_config


def quantize(value: np.ndarray) -> np.ndarray:
    return np.rint(np.clip(value[..., :3], 0.0, 1.0) * 255.0).astype(np.uint8)


def differences(reference: np.ndarray, candidate: np.ndarray) -> dict:
    """Compare display-transformed RGB, before and after delivery clipping."""
    a = reference[..., :3].astype(np.float64)
    b = candidate[..., :3].astype(np.float64)
    delta = b - a
    absolute = np.abs(delta)
    qa, qb = quantize(reference).astype(np.int16), quantize(candidate).astype(np.int16)
    quantized_difference = np.abs(qb - qa)
    clipped_mse = float(np.square(np.clip(b, 0, 1) - np.clip(a, 0, 1)).mean())
    return {
        "domain": "Display-transformed RGB before clipping; not linear scene radiance.",
        "all_finite": bool(np.isfinite(a).all() and np.isfinite(b).all()),
        "mean_absolute_error": float(absolute.mean()),
        "root_mean_square_error": float(np.sqrt(np.square(delta).mean())),
        "maximum_absolute_error": float(absolute.max()),
        "p95_absolute_channel_error": float(np.quantile(absolute, .95)),
        "p99_absolute_channel_error": float(np.quantile(absolute, .99)),
        "mean_signed_difference_rgb": delta.mean(axis=(0, 1)).tolist(),
        "fraction_channels_above_1_over_255": float((absolute > 1 / 255).mean()),
        "fraction_channels_above_5_over_255": float((absolute > 5 / 255).mean()),
        "clipped_rgb_psnr_db": None if clipped_mse == 0 else float(-10 * math.log10(clipped_mse)),
        "clipped_rgb_exact_match": clipped_mse == 0,
        "quantized_mean_absolute_error_0_255": float(quantized_difference.mean()),
        "quantized_maximum_error_0_255": int(quantized_difference.max()),
        "quantized_changed_channels": int(np.count_nonzero(quantized_difference)),
        "quantized_changed_pixels": int(np.count_nonzero(np.any(quantized_difference, axis=-1))),
        "total_pixels": int(a.shape[0] * a.shape[1]),
    }


def save_difference(reference: np.ndarray, candidate: np.ndarray, path: Path) -> None:
    """Save an explicitly amplified absolute-difference visualization."""
    error = np.abs(candidate[..., :3] - reference[..., :3])
    pixels = np.rint(np.clip(error * 8.0, 0, 1) * 255).astype(np.uint8)
    Image.fromarray(pixels).save(path)


def release_render_pass(engine: Engine) -> None:
    # Keep one context and one cached volume alive across all comparisons.
    for name in ("fbo", "vao", "p"):
        item = getattr(engine, name, None)
        if item is not None:
            item.release()
            setattr(engine, name, None)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scene", choices=("erosion", "cinematic"))
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--width", type=int, default=32)
    parser.add_argument("--height", type=int, default=18)
    parser.add_argument("--times", type=float, nargs="+", default=[0.0, 5.0, 239 / 24])
    parser.add_argument("--step", type=float, help="Cached step override; direct shader retains its delivered step.")
    parser.add_argument("--half-step", action="store_true", help="Also compare the cached step against half that step.")
    args = parser.parse_args()
    if args.width < 1 or args.height < 1 or not all(math.isfinite(t) for t in args.times):
        parser.error("Dimensions must be positive, and times must be finite.")

    cfg, source = load_config(args.scene)
    step = cfg["view_step"] if args.step is None else args.step
    minimum_step = step / 2 if args.half_step else step
    if not math.isfinite(step) or step <= 0 or math.ceil(cfg["max_distance"] / minimum_step) + 2 > 6000:
        parser.error("The requested cached step must be positive and fit the renderer's 6,000-iteration bound.")

    args.output.mkdir(parents=True, exist_ok=True)
    direct_source = ROOT / "src" / ("erosion-flight.glsl" if args.scene == "erosion" else cfg["source"])
    started = time.monotonic()
    engine = Engine(cfg, source)
    direct_values, cached_values, records = [], [], []
    try:
        engine.configure_renderer(args.width, args.height, direct=True)
        for index, seconds in enumerate(args.times):
            stem = f"sample-{index:03d}-t{seconds:.6f}"
            image, record = engine.draw(seconds)
            target = args.output / f"{stem}-direct.png"
            image.save(target)
            direct_values.append(engine.last_float.copy())
            records.append({"time": seconds, "stem": stem, "direct_file": target.name, "direct_render": record})
            print(json.dumps({"stage": "direct", "time": seconds, "seconds": record["render_seconds"]}), flush=True)
        release_render_pass(engine)

        engine.load_cache(args.cache)
        engine.configure_renderer(args.width, args.height, step=step, direct=False)
        for index, seconds in enumerate(args.times):
            image, record = engine.draw(seconds)
            stem = records[index]["stem"]
            target = args.output / f"{stem}-cached.png"
            error_target = args.output / f"{stem}-cache-error-x8.png"
            image.save(target)
            value = engine.last_float.copy()
            cached_values.append(value)
            metrics = differences(direct_values[index], value)
            save_difference(direct_values[index], value, error_target)
            records[index].update(cached_file=target.name, cache_error_file=error_target.name,
                                  cached_render=record, direct_vs_cache=metrics)
            print(json.dumps({"stage": "direct_vs_cache", "time": seconds, **metrics}), flush=True)
        release_render_pass(engine)

        if args.half_step:
            engine.configure_renderer(args.width, args.height, step=step / 2, direct=False)
            for index, seconds in enumerate(args.times):
                image, record = engine.draw(seconds)
                stem = records[index]["stem"]
                target = args.output / f"{stem}-cached-half-step.png"
                error_target = args.output / f"{stem}-step-error-x8.png"
                image.save(target)
                value = engine.last_float.copy()
                metrics = differences(value, cached_values[index])
                save_difference(value, cached_values[index], error_target)
                records[index].update(half_step_file=target.name, step_error_file=error_target.name,
                                      half_step_render=record, half_step_reference_vs_cached_step=metrics)
                print(json.dumps({"stage": "half_step_vs_step", "time": seconds, **metrics}), flush=True)
            release_render_pass(engine)

        result = {
            "scene": args.scene,
            "dimensions": [args.width, args.height],
            "cached_step": step,
            "direct_shader_step": cfg["view_step"],
            "half_step_compared": args.half_step,
            "scope": "Matched native pixel dimensions and times. Accuracy is measured at these samples only; this is not a full-film quality guarantee.",
            "error_visualization_scale": 8.0,
            "cache": str(args.cache.resolve()),
            "cache_sha256": engine.cache_hash,
            "cache_grid": list(engine.grid),
            "cache_voxel_spacing": engine.cache_meta["voxel_spacing"],
            "cache_adapter_sha256": cfg["source_sha256"],
            "direct_source": str(direct_source.resolve()),
            "direct_source_sha256": digest(direct_source.read_bytes()),
            "renderer": engine.ctx.info["GL_RENDERER"],
            "total_seconds": time.monotonic() - started,
            "records": records,
            "all_finite": all(r["direct_vs_cache"]["all_finite"] and
                              r.get("half_step_reference_vs_cached_step", {}).get("all_finite", True)
                              for r in records),
        }
        output = args.output / "comparison.json"
        output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
        print(json.dumps({"stage": "complete", "report": str(output.resolve()), "all_finite": result["all_finite"]}), flush=True)
    finally:
        engine.ctx.release()


if __name__ == "__main__":
    main()
