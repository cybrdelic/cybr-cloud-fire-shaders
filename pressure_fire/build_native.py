"""Build with CMake's platform compiler discovery; no downloaded compiler/binary."""
from pathlib import Path
import hashlib
import os
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent

def build():
    cmake = shutil.which('cmake')
    if not cmake:
        raise RuntimeError('CMake 3.20+ and a C++17 compiler are required. Windows: Visual Studio Build Tools C++; macOS: Xcode command line tools; Linux: GCC or Clang. No tools are installed automatically.')
    key = hashlib.sha256(str(ROOT).encode()).hexdigest()[:12]
    directory = Path(os.environ.get('CYBR_BUILD_DIR', str(Path(tempfile.gettempdir())/'cybr-pressure'/key)))
    subprocess.run([cmake,'-S',str(ROOT),'-B',str(directory),'-DCMAKE_BUILD_TYPE=Release'],check=True)
    subprocess.run([cmake,'--build',str(directory),'--config','Release','--parallel','2'],check=True)
    name = 'euler.exe' if os.name == 'nt' else 'euler'
    for path in [directory/'bin'/'Release'/name,directory/'bin'/name]:
        if path.is_file(): return path.resolve()
    raise RuntimeError('CMake succeeded but its solver executable is missing')

if __name__ == '__main__': print(build())
