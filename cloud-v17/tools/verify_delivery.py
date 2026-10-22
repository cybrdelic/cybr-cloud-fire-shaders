#!/usr/bin/env python3
"""Verify a complete rendered PNG sequence and its encoded MP4.

Hashes current shader and cache bytes, regenerates the renderer's exact runtime
source without creating a GPU context, checks every PNG/metadata pair, then
probes and strictly decodes every MP4 frame. Defaults require 240 unique 720p
frames at 24 fps. A failed check writes a failed report and exits nonzero.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import subprocess
import sys
from types import SimpleNamespace

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]


class VerificationError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise VerificationError(message)


def sha_bytes(value):
    return hashlib.sha256(value).hexdigest()


def hash_file(path):
    before = path.stat()
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            value.update(block)
    after = path.stat()
    require((before.st_size, before.st_mtime_ns, before.st_ino) ==
            (after.st_size, after.st_mtime_ns, after.st_ino),
            f"File changed during verification: {path}")
    return value.hexdigest()


def read_json(path):
    return json.loads(path.read_bytes())


def renderer_module(path):
    spec = importlib.util.spec_from_file_location("cloud_delivery_renderer", path)
    require(spec is not None and spec.loader is not None, "Cannot import renderer")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def runtime_hash_without_drawing(module, configuration, source, cache_meta,
                                 width, height, step):
    """Capture configure_renderer's generated source through a no-GL backend.

    This reuses the renderer's actual source-generation method, rather than a
    second copy of its formatting. No Engine.__init__, EGL, texture upload,
    shader compilation, or draw is invoked.
    """
    engine = module.Engine.__new__(module.Engine)
    engine.cfg = configuration
    engine.source = source
    engine.brick_grid = tuple(cache_meta["occupancy_grid"])
    engine.ctx = SimpleNamespace(simple_framebuffer=lambda *args, **kwargs: None)
    engine.texture = SimpleNamespace(use=lambda *args, **kwargs: None)
    engine.occupancy = SimpleNamespace(use=lambda *args, **kwargs: None)
    captured = {}

    def capture(shader):
        captured["source"] = shader
        return defaultdict(lambda: SimpleNamespace(value=None)), None

    engine.program = capture
    engine.configure_renderer(width, height, step, False)
    require("source" in captured, "Renderer did not generate its runtime source")
    actual = sha_bytes(captured["source"].encode())
    require(actual == engine.runtime_hash, "Renderer runtime hash is internally inconsistent")
    return actual


def validate_cache(args, report):
    require(args.cache.is_file(), f"Missing cache: {args.cache}")
    metadata_path = args.cache.with_suffix(".json")
    require(metadata_path.is_file(), f"Missing cache metadata: {metadata_path}")
    metadata = read_json(metadata_path)
    module = renderer_module(args.renderer)
    configuration, source = module.load_config(args.scene)
    source_path = module.ROOT / "src" / configuration["source"]
    source_hash = hash_file(source_path)
    require(configuration["source_sha256"] == source_hash, "Current source hash is inconsistent")
    require(metadata.get("configuration") == configuration,
            "Cache configuration does not exactly match current source/render settings")
    grid = metadata.get("grid", [])
    require(len(grid) == 3 and all(isinstance(v, int) and v > 0 for v in grid), "Invalid cache grid")
    require(metadata.get("dtype") == "f2" and metadata.get("channels") == 2,
            "Expected two float16 cache channels")
    expected_size = math.prod(grid) * 2 * 2
    require(args.cache.stat().st_size == expected_size, "Cache byte count does not match grid")
    cache_hash = hash_file(args.cache)
    require(cache_hash == metadata.get("cache_sha256"), "Cache byte hash differs from cache metadata")
    occupancy_path = args.cache.with_suffix(".occupancy.bin")
    require(occupancy_path.is_file(), "Missing cache occupancy file")
    occupancy_grid = metadata.get("occupancy_grid", [])
    require(len(occupancy_grid) == 3 and all(isinstance(v, int) and v > 0 for v in occupancy_grid),
            "Invalid cache occupancy grid")
    require(occupancy_path.stat().st_size == math.prod(occupancy_grid) * 2,
            "Cache occupancy byte count differs from grid")
    chosen_step = float(args.step if args.step is not None else configuration["view_step"])
    runtime_hash = runtime_hash_without_drawing(module, configuration, source, metadata,
                                               args.width, args.height, chosen_step)
    report["source"] = {"file": str(source_path.resolve()), "sha256": source_hash}
    report["renderer_source_sha256"] = hash_file(args.renderer)
    report["runtime"] = {
        "sha256": runtime_hash, "step": chosen_step,
        "derivation": "Current renderer's configure_renderer method, captured through a no-GL backend; no draw",
    }
    report["cache"] = {
        "file": str(args.cache.resolve()), "sha256": cache_hash,
        "metadata_sha256": hash_file(metadata_path),
        "grid": grid, "dtype": "f2", "channels": 2,
        "bytes": expected_size, "occupancy_sha256": hash_file(occupancy_path),
        "occupancy_grid": occupancy_grid,
        "configuration": configuration,
        "approximation": metadata.get("approximation"),
    }
    return source_hash, runtime_hash, cache_hash, chosen_step


def validate_pngs(args, report, expected):
    source_hash, runtime_hash, cache_hash, chosen_step = expected
    require(args.frames.is_dir(), f"Missing frame directory: {args.frames}")
    pattern = re.compile(r"^frame(\d{6})\.png$")
    images = {int(pattern.match(path.name).group(1)): path
              for path in args.frames.glob("frame*.png") if pattern.match(path.name)}
    desired = set(range(args.count))
    require(set(images) == desired,
            f"PNG indices differ from 0..{args.count-1}: missing={sorted(desired-set(images))}, extra={sorted(set(images)-desired)}")
    metadata_pattern = re.compile(r"^frame(\d{6})\.json$")
    metadata_indices = {int(metadata_pattern.match(path.name).group(1))
                        for path in args.frames.glob("frame*.json") if metadata_pattern.match(path.name)}
    require(metadata_indices == desired, "Frame metadata indices do not exactly match expected PNG indices")
    records, hashes = [], []
    for index in range(args.count):
        image_path = images[index]
        metadata_path = image_path.with_suffix(".json")
        metadata = read_json(metadata_path)
        time = index / float(args.fps)
        prefix = f"Frame {index}: "
        require(metadata.get("index") == index, prefix + "metadata index mismatch")
        require(isinstance(metadata.get("time"), (int, float)) and
                math.isclose(metadata["time"], time, rel_tol=0, abs_tol=1e-8), prefix + "timestamp mismatch")
        require(metadata.get("width") == args.width and metadata.get("height") == args.height,
                prefix + "metadata dimensions mismatch")
        require(metadata.get("source_sha256") == source_hash, prefix + "source hash mismatch")
        require(metadata.get("runtime_sha256") == runtime_hash, prefix + "runtime hash mismatch")
        require(metadata.get("cache_sha256") == cache_hash, prefix + "cache hash mismatch")
        require(metadata.get("direct") is False, prefix + "expected cached renderer record")
        require(metadata.get("all_finite") is True, prefix + "renderer did not record finite float output")
        require(isinstance(metadata.get("step"), (float, int)) and
                math.isclose(metadata["step"], chosen_step, rel_tol=0, abs_tol=1e-12),
                prefix + "view-step mismatch")
        mean = metadata.get("mean_rgb", [])
        require(len(mean) == 3 and all(isinstance(v, (int, float)) and math.isfinite(v) for v in mean),
                prefix + "nonfinite or missing recorded mean RGB")
        with Image.open(image_path) as image:
            require(image.format == "PNG", prefix + "not a PNG image")
            image.load()
            require(image.mode == "RGB", prefix + "expected native RGB pixels")
            require(image.size == (args.width, args.height), prefix + "decoded dimensions mismatch")
            pixels_hash = sha_bytes(image.tobytes())
        require(pixels_hash == metadata.get("pixel_sha256"), prefix + "decoded PNG pixel hash mismatch")
        hashes.append(pixels_hash)
        records.append({"index": index, "time": time, "pixel_sha256": pixels_hash,
                        "png_sha256": hash_file(image_path), "metadata_sha256": hash_file(metadata_path)})
    require(len(set(hashes)) == args.count, "PNG sequence contains repeated decoded frames")
    report["png_sequence"] = {
        "directory": str(args.frames.resolve()), "count": args.count,
        "unique_decoded_rgb_frames": len(set(hashes)), "width": args.width, "height": args.height,
        "all_indices_present": True, "all_timestamps_match": True,
        "all_source_runtime_cache_hashes_match": True,
        "all_decoded_pixel_hashes_match": True,
        "all_renderer_records_assert_finite_float_output": True,
        "scope": "PNG pixels and recorded provenance verified; float buffers are not retained and cannot be rechecked from PNGs",
        "frames": records,
    }


def run_checked(command, timeout=300):
    process = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    require(process.returncode == 0,
            command[0] + " failed: " + process.stderr[-6000:])
    return process


def validate_video(args, report):
    require(args.video.is_file(), f"Missing encoded video: {args.video}")
    probe_command = ["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
                     "-show_entries", "stream=codec_name,width,height,r_frame_rate,avg_frame_rate,nb_frames,nb_read_frames,duration,start_time:format=duration",
                     "-of", "json", str(args.video)]
    probe = json.loads(run_checked(probe_command).stdout)
    require(len(probe.get("streams", [])) == 1, "Expected one selected video stream")
    stream = probe["streams"][0]
    require(stream.get("width") == args.width and stream.get("height") == args.height,
            "Encoded video dimensions mismatch")
    for key in ("r_frame_rate", "avg_frame_rate"):
        require(Fraction(stream[key]) == args.fps, f"Encoded {key} mismatch")
    require(int(stream.get("nb_read_frames", -1)) == args.count, "ffprobe decoded frame count mismatch")
    if stream.get("nb_frames") not in (None, "N/A"):
        require(int(stream["nb_frames"]) == args.count, "Container frame count mismatch")
    duration = float(stream.get("duration", probe.get("format", {}).get("duration", "nan")))
    expected_duration = args.count / float(args.fps)
    require(math.isclose(duration, expected_duration, rel_tol=0, abs_tol=0.001),
            f"Encoded duration mismatch: {duration} versus {expected_duration}")
    require(abs(float(stream.get("start_time", 0))) < 0.001, "Encoded video does not begin at time zero")
    decode_command = ["ffmpeg", "-v", "error", "-xerror", "-err_detect", "explode",
                      "-i", str(args.video), "-map", "0:v:0", "-an", "-sn", "-dn",
                      "-pix_fmt", "rgb24", "-fps_mode", "passthrough", "-f", "framemd5", "-"]
    decoded = run_checked(decode_command)
    timebase = None
    frames = []
    for line in decoded.stdout.splitlines():
        if line.startswith("#tb 0:"):
            timebase = Fraction(line.split(":", 1)[1].strip())
        if not line or line.startswith("#"):
            continue
        pieces = [piece.strip() for piece in line.split(",")]
        require(len(pieces) == 6, "Unexpected ffmpeg frame-hash line")
        stream_index, dts, pts, frame_duration, size = map(int, pieces[:5])
        require(stream_index == 0, "Unexpected decoded stream index")
        require(size == args.width * args.height * 3, "Decoded RGB frame byte count mismatch")
        frames.append({"index": len(frames), "dts": dts, "pts": pts,
                       "duration": frame_duration, "rgb_md5": pieces[5]})
    require(timebase is not None, "Missing decoded frame timebase")
    require(len(frames) == args.count, "Strict decode frame count mismatch")
    require(len({frame["rgb_md5"] for frame in frames}) == args.count,
            "Encoded video contains repeated decoded RGB frames")
    for index, frame in enumerate(frames):
        expected_time = Fraction(index, 1) / args.fps
        require(frame["pts"] * timebase == expected_time,
                f"Decoded frame {index} presentation timestamp mismatch")
        require(frame["duration"] * timebase == 1 / args.fps,
                f"Decoded frame {index} duration mismatch")
    report["video"] = {
        "file": str(args.video.resolve()), "sha256": hash_file(args.video),
        "bytes": args.video.stat().st_size, "ffprobe": probe,
        "strict_ffmpeg_decode_passed": True, "strict_decode_stderr": decoded.stderr,
        "decoded_pixel_format": "rgb24", "decoded_count": len(frames),
        "unique_decoded_frames": len({frame["rgb_md5"] for frame in frames}),
        "frame_hash_algorithm": "MD5 of decoded RGB24 pixels (ffmpeg framemd5)",
        "decoded_timebase": str(timebase), "all_decoded_timestamps_match": True,
        "duration_seconds": duration, "frames": frames,
        "scope": "Full strict decode, dimensions, cadence, count, and uniqueness; lossy encoding changes pixels, so decoded MP4 hashes are not equated to PNG hashes",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scene", choices=("cinematic", "erosion"))
    parser.add_argument("frames", type=Path)
    parser.add_argument("video", type=Path)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--renderer", type=Path, default=ROOT / "tools/render_clouds.py")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--count", type=int, default=240)
    parser.add_argument("--fps", type=Fraction, default=Fraction(24, 1))
    parser.add_argument("--step", type=float)
    args = parser.parse_args()
    if args.output is None:
        args.output = ROOT / "validation" / f"{args.scene}-delivery.json"
    report = {
        "scene": args.scene, "passed": False,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "expected": {"count": args.count, "width": args.width, "height": args.height,
                     "fps": str(args.fps), "duration_seconds": args.count / float(args.fps)},
        "provenance": "Newly rendered reconstructed continuation; not resumed original V17 frames",
    }
    try:
        require(args.count > 0 and args.fps > 0 and args.width > 0 and args.height > 0,
                "Count, frame rate, and dimensions must be positive")
        expected = validate_cache(args, report)
        validate_pngs(args, report, expected)
        validate_video(args, report)
        report["passed"] = True
    except Exception as error:
        report["error_type"] = type(error).__name__
        report["error"] = str(error)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": report["passed"], "report": str(args.output.resolve()),
                      "scene": args.scene, "png_frames": report.get("png_sequence", {}).get("count"),
                      "video_frames": report.get("video", {}).get("decoded_count"),
                      "error": report.get("error")}, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
