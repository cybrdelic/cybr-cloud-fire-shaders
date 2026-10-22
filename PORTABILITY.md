# Running on Windows, macOS and Linux

The browser previews need a current browser with WebGL2 and a working graphics driver. Serve the repository with `python -m http.server 8000` and open `http://localhost:8000/cloud-v17/cloud-flight.html`. The controls adapt to narrow screens; Auto adjusts preview resolution, and explicit resolutions remain selectable. This is not a physical mobile-GPU qualification. The MP4 links are historical offline renders, not captures of the current preview.

For native Python tools, install Python 3.12 and create an isolated environment:

```sh
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\python -m pip install -r cloud-v17/requirements.txt
# macOS/Linux:
.venv/bin/python -m pip install -r cloud-v17/requirements.txt
```

Use that environment's Python for the following commands. Windows contexts use WGL, macOS uses CGL, and Linux tries EGL then a display-backed context. The tools require OpenGL 3.3. macOS does not support native OpenGL versions beyond 4.1. A headless Linux machine needs working EGL/Mesa libraries or an X display. `CYBR_GL_BACKEND=egl` or `default` can select an existing backend; no driver or system package is installed by these tools.

```sh
python cloud-v17/tools/build_player.py
python cloud-v17/tools/verify_player.py --output verification.json
python cloud-v17/tools/render_clouds.py erosion render --direct --cache unused-cache.bin --output smoke --width 16 --height 9 --times 0
```

The verifier reports `compiler_kind`: native GLES where available, otherwise an explicitly identified desktop GLSL 3.30 adaptation. Desktop syntax checks replace the version/precision preamble and namespace the user-defined scalar `noise3` function, which collides with a desktop GLSL builtin. Its body and call arguments are unchanged. These checks are **not WebGL browser validation**. The direct smoke render bypasses the large lattice cache and does not demonstrate a production film.

The player builder normalizes Windows CRLF checkout newlines to LF before embedding and hashing source. This changes no GLSL tokens and makes generated payloads independent of Git's checkout newline setting. The manifest records that normalization and uses portable output names instead of local machine paths.

The pressure solver needs CMake 3.20+ and an installed C++17 compiler: Visual Studio Build Tools with C++ on Windows, Xcode command line tools on macOS, or GCC/Clang on Linux. `python pressure_fire/build_native.py` discovers the platform compiler and builds into a short temporary path. `CYBR_BUILD_DIR` overrides that location. CMake honors its normal compiler configuration, including `CXX` for a new build directory. MSVC runs this solver in serial mode because its classic OpenMP version lacks the required reductions. Other compilers use OpenMP when available; serial mode retains the equations.

```sh
python -m unittest discover -s tests -v
python tests/solver_smoke.py
python -m pip install playwright==1.63.0
python -m playwright install chromium
python tests/browser_smoke.py
```

The CI matrix runs core tests, the small C++ simulation and browser checks on Windows, macOS and Linux. CI configuration is not evidence that remote CI has already passed. Native GPU drivers vary; hosted CI browser execution is not a hardware-performance benchmark.

The historical `cloud-v17/src/check_essl.py` and `check_cloud_essl.py` are Linux EGL diagnostic scripts. Use the maintained portable `tools/verify_player.py` and actual browser checks above for current validation. No renderer equation, integration rule, simulation model, existing license or historical media is replaced by the portability layer.
