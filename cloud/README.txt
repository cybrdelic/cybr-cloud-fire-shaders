CLOUD FIELD FLIGHT — 497-character FragCoord shader

The complete cloud-flight.fragcoord.txt is exactly 497 ASCII characters,
including density, camera, light, integration and output. Expanded GLSL and
the HTML viewer are outside that count. The live shader uses no textures,
external noise assets or additional passes.

PLAY
Open cloud-flight.html in a WebGL2 browser. Pause, Restart and the time slider
cover the ten-second flight. Quality caps width at 480, 960 or 1600 pixels;
performance depends on the GPU and browser. Paste the compact source into
FragCoord's GOLF editor. cloud-flight-link.json retains its exact-source link.

SCENE AND SAMPLING
Rounded cloud envelopes repeat across the horizontal world at 16-unit spacing.
The billows use continuous world-space noise, so the cloud shapes differ across
the field. There is no hard horizontal density cutoff. The camera descends
from y=7 to y=5 while advancing ten units between and along the formations.
This is a static procedural density field seen by a moving camera. It is not
a fluid solver, pressure simulation or model of atmospheric convection.

Each Worley octave searches 27 neighboring cells and caps nearest-point
distance at 1. That cap keeps neighborhood changes continuous. Primary density
uses up to six octaves; shadows use up to four. The early exit is conservative:
it stops only when the positive contribution of all remaining octaves cannot
make the density positive. No random temporal jitter is used.

The marcher uses up to 2000 midpoint samples at 1/32-unit spacing, covering
62.5 units, and 64 midpoint sun probes per occupied primary sample. Primary
extinction is exp(-density/11); the shadow sum is weighted by .167. Distance
haze blends cloud color toward sky color with a 31.25-unit exponential scale.

OFFLINE VIDEO APPROXIMATION
The delivered cloud-flight-v16.mp4 is a ten-second, native 1280 x 720 render at
24 fps. Each of its 240 frames is shaded separately. Its offline renderer uses
a fixed 1024 x 384 x 896 world-space cache over [-42,-14,-2] to [48,14,74].
It stores density and density-weighted light transmittance in two float16
channels, then reconstructs them with trilinear interpolation. Shadow lighting
is integrated through the sampled shadow-density field. This smooths the
smallest features and rounds values to float16; the cache is an approximation
of the procedural shader, not an additional part of the compact scene.

The delivered video also uses conservative empty-brick skipping. A brick is
skippable only if all of its source cache density voxels, plus a one-voxel
halo needed for trilinear filtering, are zero. Skipping retains the original
integer sample indices and their distance-haze values. Grouping additions
changes floating-point accumulation slightly: comparisons at 0, 8.4 and 9.96
seconds at 320 x 180 found a maximum difference of one 8-bit channel level;
about 0.09 to 0.13 percent of channel values differed. The largest float RGB
difference was 0.000572. These are measured checks at those times, not a claim
of bitwise equality for every pixel. See audits/fast-cache-comparison.json.
The original unaccelerated cache renderer remains included.

There is no frame interpolation, temporal averaging, image upscaling or
AI-generated imagery. The live player evaluates the procedural field directly.
The cache is rebuilt from the source and is not bundled. It requires about
1.31 GiB of raw storage, with additional working memory during generation and
rendering. Use two rendering workers with this grid to limit memory use.
Source hashes, grid, bounds, optical parameters and cache format guard reuse.
Out-of-cache probes evaluate the source directly. cache_domain.py proves that
the cache boundaries do not cross nonzero density in the selected ten-second
16:9 view; changed sources must pass that proof again or use reviewed bounds.

VALIDATION SCOPE
The player embeds the supplied compact and expanded sources exactly. Its
JavaScript parses, its source link roundtrips, and the actual player shader
preamble compiles and links under native OpenGL ES 3. This is not a browser
or ANGLE runtime test. The build and GLES JSON files record the source hashes
and scope. Final rendering and cache-comparison evidence is supplied separately
in the current shader-verification.json and cloud audit files.

REPRODUCE (FROM THIS CLOUD FOLDER)
Install Python requirements and supply an EGL/OpenGL 3.3-capable driver.
Native shader validation also uses system EGL/GLES libraries. ffmpeg is needed
for MP4 encoding; Node.js is needed only for the JavaScript source audit.
The full shaders are included, so no FragCoord converter download is required.

  python3 -m pip install -r requirements.txt

Exact procedural still, with no cache:
  python3 render.py cloud-flight.glsl direct-preview --width 640 --height 360 --times 0

Check the selected field and ten-second cache domain:
  python3 cache_domain.py cloud-flight.glsl cache-domain.json

Build the offline cache and a preview:
  python3 cache_volume.py cloud-flight.glsl preview --grid 1024 384 896 --bounds -42 -14 -2 48 14 74 --dtype f2 --cache cloud-field.bin --width 640 --height 360 --times 0

Render the full video frames using the existing cache and empty-brick skipping:
  python3 render_film_fast.py --source cloud-flight.glsl --output frames --renderer cache --grid 1024 384 896 --bounds -42 -14 -2 48 14 74 --dtype f2 --cache cloud-field.bin --width 1280 --height 720 --count 240 --fps 24 --workers 2

Encode, stopping on a corrupt input frame:
  ffmpeg -xerror -framerate 24 -i frames/frame%06d.png -frames:v 240 -c:v libx264 -preset slow -crf 16 -pix_fmt yuv420p -movflags +faststart cloud-flight-v16.mp4

For the unaccelerated cache path, use render_film.py with the same arguments.
For exact uncached frames, choose --renderer direct and omit --grid, --bounds,
--dtype and --cache. This is substantially slower in software OpenGL. Both
renderers use times frame_index/24. GPU arithmetic may change individual pixels.

Audit the cache against direct shader output at selected times:
  python3 cache_volume.py cloud-flight.glsl cache-check --grid 1024 384 896 --bounds -42 -14 -2 48 14 74 --dtype f2 --cache cloud-field.bin --width 320 --height 180 --times 0 5 9.5 --audit

Compare accelerated and ordinary cached rendering:
  python3 compare_fast.py cloud-flight.glsl cloud-field.bin fast-check --times 0 8.4 9.96

Empty-brick occupancy files are regenerated when density, view octaves, cache
algorithm, grid, bounds, storage format, file size or modification time changes.
Their shape, dtype, binary values and checksum are checked before use. The
vertical empty-space exit is restricted to the proven selected density hash.

Rebuild and validate the player:
  python3 build_player.py cloud-flight.glsl cloud-flight.fragcoord.txt cloud-flight.html
  python3 check_cloud_essl.py cloud-flight.glsl --out cloud-gles-validation.json
  node audit_player.cjs cloud-flight.html
