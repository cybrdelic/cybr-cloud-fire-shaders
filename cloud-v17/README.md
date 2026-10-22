# Cloud Flight — V17 continuation

Two procedural cloud flights share one deliverable: a full cinematic GLSL
scene and a compact **493-character FragCoord** scene, with a standalone WebGL2
viewer and separately rendered ten-second videos.

## Recovery and provenance

This is a **new continuation built from the recovered V16 source and the V17
design described in the linked conversation**. The previous conversation's
unfinished V17 source, render cache, and frame files were not recovered. The
videos delivered with this package are newly rendered; they are not a resumed
original frame sequence.

The recovered V16 baseline is identifiable by the compact-source SHA-256
`4a410ebe5b0ef4b96358db61d08e00feb17288a1389e95dd5f76708e485ad2fa`.
The recovered V16 files included source, a 1280 × 720 / 24 fps / ten-second movie,
and verification records. It did not include its large offline cache.

The clouds are procedural density fields viewed by a moving camera. There is
no fluid solver, atmospheric convection simulation, or pressure simulation in
either cloud shader. No image generation is used to create these scenes.

## Files

| File | Purpose |
| --- | --- |
| `cinematic-cloud-flight.mp4` | Newly rendered cinematic flight |
| `erosion-flight-493.mp4` | Newly rendered compact-scene flight |
| `cloud-flight.html` | Standalone viewer with both shaders embedded |
| `src/cinematic.glsl` | Cinematic shader body with `mainImage`, used by the offline renderer |
| `src/cinematic-webgl2.glsl` | Complete GLSL ES 3.00 cinematic fragment shader, identical to the viewer runtime |
| `src/erosion-flight.glsl` | Expanded compact-scene GLSL source |
| `src/erosion-flight.fragcoord.txt` | Exact complete 493-character FragCoord source |
| `src/erosion-flight-adapter.glsl` | Compact scene expressed through the shared offline-rendering interface |
| `src/*-render.json` | Scene bounds and optical/integration parameters |
| `requirements.txt` | Versions used for the Python rendering environment |
| `tools/render_clouds.py` | Cache generation and independent-frame rendering for both scenes |
| `tools/build_player.py` | Rebuilds the viewer from the delivered sources |
| `tools/verify_player.py` | Checks source embedding and compiles both actual runtime shaders with native GLES 3 |
| `tools/verify_delivery.py` | Verifies frame provenance, PNG pixels, cache bytes, and the complete encoded video |
| `cloud-flight.build.json` | Viewer source hashes and build scope |

The delivery reports in `validation/` describe the encoded movies that passed
the checks. Large binary caches and the raw PNG sequences are rebuilt locally
with the commands below; they are excluded from the compact source/video
package. The small cache metadata JSON files are retained as provenance.

## View the flights

Open either MP4 for the fully rendered animation. Keep the MP4s beside the
HTML file if you want its video-download links to work.

Open `cloud-flight.html` in a WebGL2 browser for an interactive shader preview.
Choose a scene, then use **Play**, **Pause**, **Restart**, or the time slider.
Both scene timelines cover ten seconds. The preview starts paused and requests
one initial frame. When the page is hidden, animation time stops advancing.

The **Auto** preview setting starts at 320 pixels wide on a desktop pointer or
240 pixels on a coarse pointer, reducing toward 160 pixels when frames are
slow. You can select a fixed resolution up to 960 pixels wide. Preview speed
depends on the device, driver, shader, and browser; the player does not promise
real-time playback. A visible compilation or context error includes the
browser's diagnostic text.

The preview timeline advances only when the graphics queue is ready to submit
the next frame, by at most 1/24 second per draw. A slow device therefore plays
the path more slowly instead of advancing several seconds while one frame is
still rendering. Completing the preview can take longer than ten seconds of
wall-clock time; the encoded MP4 duration is ten seconds.

The viewer is self-contained and makes no network requests. Its relative MP4
links load only when selected. **Source & downloads** exports the complete
cinematic WebGL2 fragment shader or the exact expanded erosion GLSL. It also
exposes the compact source for copying or downloading. Both original GLSL
inputs remain embedded unchanged in the viewer and included in `src/`.

## Character count

The 493-character count applies only to the complete ASCII contents of
`src/erosion-flight.fragcoord.txt`: density construction, camera, lighting,
integration, and output. The cinematic shader, expanded GLSL, viewer, rendering
tools, and any offline acceleration data are outside that count.

The player build rejects a compact file whose exact content is not 493 ASCII
characters. It does not trim whitespace, remove comments, or alter the source
to meet the count.

The expanded compact GLSL was written using the recovered FragCoord GOLF
semantics and then checked against the official converter bundle served by
FragCoord. The unchanged converter recognizes the 493-character source as
GOLF and expands its bounded loops, inverse operator and zero initializers
as intended. Its own URL decoder accepts the generated `#code` link and
returns the exact source. The converted output compiles and links in native
GLES 3. This is a local execution of the official converter followed by native
compilation, not a live-browser playback test. Evidence is recorded in
`validation/compact/fragcoord-compiler-validation.json` and the corresponding
converted GLSL and GLES report. The native shader and shared-renderer adapter
were also compared separately at three sampled times; their report records
the dimensions and numerical differences.

## Dependencies and renderer environment

The Python renderer was run on **Python 3.12**, using **ModernGL 5.13.0**,
**glcontext 3.1.0**, **NumPy 2.3.5**, **Pillow 12.3.0**, and **SciPy 1.17.0**.
The reproducible requirements file pins those versions.

The rendering scripts use the **EGL** backend and require an OpenGL 3.3-capable
implementation. Native shader verification additionally requires the system
EGL/GLES libraries. `ffmpeg` and `ffprobe` handle encoding/decoding; Node.js is
used only for JavaScript syntax verification. A WebGL2 browser is needed only
for the interactive HTML preview.

This run used Linux Mesa **llvmpipe (LLVM 20.1.2, 256 bits)**, a software
renderer, with an eight-core CPU quota and an 8 GiB memory limit. No hardware
GPU was exposed to EGL. These are the production environment's resources,
not a browser-performance guarantee or a claim that an arbitrary machine
will render at the same speed. Floating-point differences across drivers can
change individual pixels and cache hashes.

Create an isolated Python environment and install the rendering dependencies:

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
```

Install `ffmpeg`, `ffprobe`, Node.js, and the EGL/GLES system libraries through
your platform's normal package manager. The scripts target the tested
headless EGL environment; other systems must supply a working EGL driver.

## Reproduce the offline videos

Run the following commands from this directory. Both movies contain **240
separately evaluated frames**, sampled at `frame_index / 24`, for **10 seconds
at 24 fps and 1280 × 720 native output pixels**. The final sample is at
`239/24` seconds. There is no frame interpolation, image enlargement, or
image-generated content in these commands.

| Scene | Cache grid, X × Y × Z | Cached positions | Two-channel float16 cache bytes | View step |
| --- | ---: | ---: | ---: | ---: |
| Cinematic | 768 × 384 × 1024 | 301,989,888 | 1,207,959,552 (1.125 GiB) | 0.065 |
| Erosion | 896 × 384 × 800 | 275,251,200 | 1,101,004,800 (1.0254 GiB) | 0.03125 |

Those byte counts are for the final density/light fields alone. Baking also
uses a temporary density field, GPU/driver allocations, occupancy data, and
working memory. Run the two scenes sequentially as shown to avoid keeping
both large working sets alive at once.

First bake and render the cinematic scene:

```bash
python3 tools/render_clouds.py cinematic bake \
  --cache cache/cinematic-final.bin --grid 768 384 1024

python3 tools/render_clouds.py cinematic render \
  --cache cache/cinematic-final.bin --output frames/cinematic \
  --width 1280 --height 720 --count 240 --fps 24 --step 0.065

ffmpeg -xerror -framerate 24 -i frames/cinematic/frame%06d.png \
  -frames:v 240 -c:v libx264 -preset slow -crf 16 \
  -pix_fmt yuv420p -movflags +faststart cinematic-cloud-flight.mp4
```

Then bake and render the compact scene:

```bash
python3 tools/render_clouds.py erosion bake \
  --cache cache/erosion-final.bin --grid 896 384 800

python3 tools/render_clouds.py erosion render \
  --cache cache/erosion-final.bin --output frames/erosion \
  --width 1280 --height 720 --count 240 --fps 24 --step 0.03125

ffmpeg -xerror -framerate 24 -i frames/erosion/frame%06d.png \
  -frames:v 240 -c:v libx264 -preset slow -crf 16 \
  -pix_fmt yuv420p -movflags +faststart erosion-flight-493.mp4
```

An interrupted frame run can use the same render command again: the renderer
checks its saved runtime/cache hashes, dimensions, sample time, and decoded
PNG pixel hash before reusing an existing frame. PNGs are encoded in memory,
written atomically, and checked against their encoded byte hash before commit. Always run the independent delivery verifier after
resuming. Cache generation must complete before the render command is run.

For a small uncached reference sample, use `--direct`. The required `--cache`
argument is not read by that mode. The compact scene's direct mode evaluates
its expanded compact GLSL; it does not substitute the cached renderer:

```bash
python3 tools/render_clouds.py erosion render --direct \
  --cache cache/erosion-final.bin --output direct-reference/erosion \
  --width 32 --height 18 --times 0 5 9.958333333333334
```

Exact procedural rendering is substantially more expensive than the cached
movie path on the measured software renderer. The small reference dimensions
are deliberate; they do not describe the native resolution of the MP4s.

## Rebuild the viewer

From this directory:

```bash
python3 tools/build_player.py
```

That command reads both GLSL files and the compact source, embeds them in
`cloud-flight.html`, writes `cloud-flight.build.json`, and exports the complete
cinematic runtime to `src/cinematic-webgl2.glsl`. No third-party Python packages
are required for the viewer build. Custom input/output paths are available
through `--cinematic`, `--erosion`, `--compact`, `--output`, and
`--cinematic-webgl-output`.
Use `--no-video-links` when distributing the HTML without the MP4 files.

The runtime shader is adapted to GLSL ES 3.00 with a precision preamble and
any missing standard uniforms. A source that supplies `mainImage` without
`main` receives a small output wrapper with its own global fragment output;
an existing `main` is retained. The original source embedding is byte-for-byte
identical to its input. The cinematic GLSL download includes this wrapper and
is byte-for-byte identical to the runtime compiled by the viewer; the erosion
download is its already complete expanded GLSL input. The build manifest
distinguishes original-source, runtime, and download hashes. This wrapper does
not enter the compact character count.

Validate that built player without rendering frames:

```bash
python3 tools/verify_player.py
```

This checks exact source embedding, the standalone cinematic runtime export,
JavaScript parsing with Node.js, and native EGL/GLES 3 compilation and linking
of the shader strings extracted from the HTML. It does not test a browser or
render a frame.

## Rendering and verification scope

The HTML evaluates its procedural shaders directly. The offline movies use
sampled world-space fields containing **density** and **density-weighted sun
optical depth**, stored as two float16 channels. Sunlight is integrated through
the sampled shadow-density field. During rendering, trilinear interpolation
reconstructs density and optical depth between cache positions. This can
soften small details and introduces float16 rounding; it is not bitwise
equivalent to direct procedural evaluation.

The offline integrator intersects finite cache bounds specified in each
`src/*-render.json` file. Its light path can also leave that sampled domain.
Those finite-domain choices and spatial reconstruction are part of the
offline approximation. The two scenes retain their own optical parameters,
camera functions, and display transforms through the shared renderer.
Empty-brick skipping avoids regions marked empty by the cached occupancy
field. There is no time-varying random sampling or interpolation between
finished animation frames. The cache is separate from the compact shader and
does not increase its claimed character budget.

The delivery reports record video dimensions, frame rate, duration, decoded
frame count, unique-frame checks, source hashes, cache identity, and the
offline approximation. Source compilation, source embedding, and video decode
checks establish different things. They do not by themselves prove that
every browser runs smoothly or that all spatial and temporal aliasing is
absent. Lighting uses approximations for scattering rather than an unbiased
volumetric path tracer.

`cloud-flight.build.json` records that a browser runtime check has not been
performed by the builder. A later QA report should identify any browser test
separately instead of changing this build-time claim without evidence.

## Verify a completed video

Once rendering and encoding are complete, pass the actual frame directory,
video, and cache to the delivery verifier. For example:

```bash
python3 tools/verify_delivery.py cinematic frames/cinematic \
  cinematic-cloud-flight.mp4 --cache cache/cinematic-final.bin

python3 tools/verify_delivery.py erosion frames/erosion \
  erosion-flight-493.mp4 --cache cache/erosion-final.bin
```

The paths match the reproduction commands above. Rebuild the binary caches
and PNG frames before running this check on a downloaded source/video package.
The default check requires 240 unique 1280 × 720 frames at 24 fps. Pass
`--step` if a rendering run used an explicit step different from its source
configuration.

The verifier independently hashes the current source and cache bytes, checks
the cache's exact source/configuration binding, and regenerates the renderer's
runtime source through a capture backend that performs no GPU work. Every PNG
must have the expected index, timestamp, dimensions, source hash, runtime hash,
cache hash, step, and matching decoded RGB pixel hash. It then checks the MP4
with `ffprobe` and a strict `ffmpeg` decode, including all decoded frame hashes,
unique-frame count, and presentation timestamps. Failure writes a failed JSON
report and exits nonzero. The report distinguishes recorded float-buffer
finiteness from checks possible on the retained PNGs.


## Measured cache approximation

Direct procedural rendering and the final cache were compared at identical
**48 × 27** pixel dimensions and three times per scene: opening, near the
middle, and the last movie sample. These are reference samples, not full-frame
error bounds for every frame of the native 720p movie.

| Scene | Mean absolute RGB error across the three sampled views | Largest individual channel difference | Mean change after halving the view step |
| --- | ---: | ---: | ---: |
| Cinematic | 0.001673–0.002846 | 0.158737 | 0.000040–0.000074 |
| Compact | 0.004536–0.005742 | 0.114859 | 0.000035–0.000049 |

Errors use display-transformed RGB on a nominal 0–1 scale. The average
cache difference corresponds to approximately 0.43–0.73 of an 8-bit code
value for the cinematic scene and 1.16–1.46 for the compact scene. Isolated
edge differences are larger, as the maximum column shows. The cache softens
some of the finest compact density detail; it does not preserve every noise
octave exactly. At these sampled views, spatial reconstruction contributes
much more error than the primary ray step. All sampled outputs were finite.

The complete numerical records and small direct/cached/difference PNGs are
in `validation/cinematic-cache/` and `validation/erosion-cache/`. Reproduce a
comparison with:

```bash
python3 tools/compare_cache.py erosion --cache cache/erosion-final.bin \
  --output validation/erosion-cache --width 48 --height 27 \
  --times 0 5 9.958333333333334 --half-step
```
