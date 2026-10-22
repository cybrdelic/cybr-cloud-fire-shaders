# CYBR Cloud & Fire Studies

Procedural cloud shaders, a standalone WebGL2 viewer, offline cloud-rendering tools, and an earlier reactive pressure-fireball study.

![Cinematic cloud flight](media/cinematic-cloud.png)

![Cinematic cloud animation](media/cinematic-cloud.gif)

The previews come from the included V17 cinematic film. The still is an actual decoded movie frame; the GIF is a 480-pixel-wide, 8 fps preview. The original movie is 1280 × 720 at 24 fps for ten seconds.

## Start here

Open `cloud-v17/cloud-flight.html` in a WebGL2-capable browser. The viewer contains both cloud shaders and needs no package installation or external assets. Keep its two MP4 files beside it to use the video-download links.

If your browser restricts local files, serve the repository:

```sh
python3 -m http.server 8000
```

Open http://localhost:8000/cloud-v17/cloud-flight.html. Choose a scene, press Play, and adjust the preview resolution as needed. The preview starts paused; its clock follows completed frames, so slow hardware can take more than ten seconds to play the full path.

For the finished offline renders, open:

- [Cinematic cloud flight](cloud-v17/cinematic-cloud-flight.mp4)
- [Compact erosion-cloud flight](cloud-v17/erosion-flight-493.mp4)

## Project layout

- `cloud-v17/`: current cinematic and compact cloud scenes, viewer, two films, renderer, pinned dependencies, and validation records.
- `cloud/`: preserved V16 cloud baseline and its supporting tools.
- `pressure_fire/`: earlier C++/Python reactive compressible-flow reference and numerical checks.
- `pressure_render/`: pressure-fireball WebGL2 viewer, GLSL passes, and rendering tools.
- `pressure-fireball-fragcoord.txt`: the earlier fireball shader export.
- `media/`: README still and GIF derived from the current cinematic movie.

The current cloud work is a reconstructed continuation from the recovered V16 design. V17's movie frames were newly rendered; this package does not claim recovery of an unfinished original V17 frame sequence.

## Cloud shaders

Both scenes use procedural density fields and a moving camera. The cinematic scene has a full GLSL implementation; the compact scene's complete FragCoord program is exactly 493 ASCII characters. That count applies only to `cloud-v17/src/erosion-flight.fragcoord.txt`, not the viewer, expanded GLSL, tools, or offline acceleration data.

The browser evaluates the procedural shaders directly. The offline movies instead interpolate a precomputed density/light cache, so they are not bitwise-equivalent direct-shader recordings. These clouds do not include a fluid solver or atmospheric-convection simulation.

## Build and reproduce

Rebuild the standalone viewer with Python's standard library:

```sh
cd cloud-v17
python3 tools/build_player.py
```

For the offline renderer, create a Python environment and install the pinned dependencies:

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
```

The documented rendering environment uses Python 3.12, ModernGL, glcontext, NumPy, Pillow, SciPy, EGL/OpenGL 3.3, and FFmpeg/ffprobe. Native shader checks also require EGL/GLES system libraries. Node.js is used for JavaScript syntax checks. Dependencies are installed separately and are not vendored here.

Full rendering commands and exact settings are in [the V17 guide](cloud-v17/README.md). Each movie has 240 independently evaluated frames. Final density/light caches alone occupy about 1.125 GiB for the cinematic scene and 1.025 GiB for erosion; baking and rendering need additional working memory and storage. Large cache binaries and raw frame sequences are intentionally absent and must be regenerated.

The earlier pressure-fireball reference requires Python with NumPy and a C++17 compiler with OpenMP. Its reproducible commands and numerical assumptions are in [the pressure-flow guide](pressure_fire/README.md). Open `pressure_render/pressure-fireball.html` for that separate WebGL2 study.

## Validation and limits

The preserved reports distinguish shader compilation, viewer embedding, cache comparisons, and encoded-video checks. Native compilation is not a browser-interaction test or a hardware-performance benchmark. Publication checks inspected source, media metadata, and sampled decoded frames; the project renderer was not rerun for publication.

The cloud renderer approximates scattering and finite-domain sampling rather than providing an unbiased volumetric path tracer. Small reference comparisons in the V17 guide do not bound the error of every full-resolution movie frame. Visual quality and browser speed remain device-dependent.

The pressure-fireball model is a nondimensional visual study with simplified reaction, buoyancy, and subgrid closures. It is not calibrated oil chemistry, a real-world blast predictor, or safety engineering software. Its behavior is distinct from the procedural cloud shaders.

## Publication notes and license

Shader and executable-source bytes are preserved. Historical machine-specific paths in seven JSON records have been normalized to project-relative paths; numerical results are unchanged. The preservation record and checksums have been refreshed for these publication copies. Historical reports can refer to large outputs that are not distributed here.

No project license was supplied in the source archive, and this publication adds no license grant. The included references in `pressure_fire/README.md` are retained. Third-party dependencies remain separately installed under their own terms.
