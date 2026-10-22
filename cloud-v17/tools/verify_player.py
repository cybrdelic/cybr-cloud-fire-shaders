#!/usr/bin/env python3
"""Check exact player embeddings and compile with native GLES or adapted desktop GL.

The selected compiler is recorded; neither native path is a browser test.
No frame is rendered by this command.
"""
from __future__ import annotations

import argparse
import ast
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from portable_gl import create_context, desktop_identifiers


ROOT = Path(__file__).resolve().parents[1]


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def json_constant(script: str, name: str):
    start = script.index("const " + name + "=") + len("const " + name + "=")
    return json.JSONDecoder().raw_decode(script[start:])[0]


class GLES:
    def __init__(self):
        os.environ.setdefault("EGL_PLATFORM", "surfaceless")
        os.environ.setdefault("MESA_SHADER_CACHE_DIR", "/tmp/cloud-render-mesa-cache")
        self.egl = C.CDLL("libEGL.so.1")
        self.V, self.I, self.U = C.c_void_p, C.c_int, C.c_uint
        V, I, U = self.V, self.I, self.U
        self.getproc = self.bind("eglGetProcAddress", V, [C.c_char_p])
        getdisplay = C.CFUNCTYPE(V, U, V, C.POINTER(I))(self.getproc(b"eglGetPlatformDisplayEXT"))
        initialize = self.bind("eglInitialize", U, [V, C.POINTER(I), C.POINTER(I)])
        choose = self.bind("eglChooseConfig", U, [V, C.POINTER(I), C.POINTER(V), I, C.POINTER(I)])
        bindapi = self.bind("eglBindAPI", U, [U])
        createcontext = self.bind("eglCreateContext", V, [V, V, V, C.POINTER(I)])
        createsurface = self.bind("eglCreatePbufferSurface", V, [V, V, C.POINTER(I)])
        self.makecurrent = self.bind("eglMakeCurrent", U, [V, V, V, V])
        self.display = getdisplay(0x31DD, None, self.attrs(0x3038))
        major, minor = I(), I()
        if not initialize(self.display, C.byref(major), C.byref(minor)):
            raise RuntimeError("EGL initialization failed")
        if not bindapi(0x30A0):
            raise RuntimeError("EGL could not bind the OpenGL ES API")
        config, count = V(), I()
        selection = self.attrs(0x3033, 1, 0x3040, 0x40, 0x3024, 8, 0x3023, 8,
                               0x3022, 8, 0x3021, 8, 0x3038)
        if not choose(self.display, selection, C.byref(config), 1, C.byref(count)) or not count.value:
            raise RuntimeError("No GLES 3 EGL configuration")
        self.context = createcontext(self.display, config, None, self.attrs(0x3098, 3, 0x3038))
        self.surface = createsurface(self.display, config, self.attrs(0x3057, 16, 0x3056, 16, 0x3038))
        if not self.context or not self.surface or not self.makecurrent(self.display, self.surface, self.surface, self.context):
            raise RuntimeError("GLES 3 context creation failed")
        self.getstring = self.gl("glGetString", C.c_char_p, U)
        self.create = self.gl("glCreateShader", U, U)
        self.shader_source = self.gl("glShaderSource", None, U, I, C.POINTER(C.c_char_p), C.POINTER(I))
        self.compile = self.gl("glCompileShader", None, U)
        self.shaderiv = self.gl("glGetShaderiv", None, U, U, C.POINTER(I))
        self.shaderlog = self.gl("glGetShaderInfoLog", None, U, I, C.POINTER(I), C.c_char_p)
        self.delete_shader = self.gl("glDeleteShader", None, U)
        self.create_program = self.gl("glCreateProgram", U)
        self.attach = self.gl("glAttachShader", None, U, U)
        self.link = self.gl("glLinkProgram", None, U)
        self.programiv = self.gl("glGetProgramiv", None, U, U, C.POINTER(I))
        self.programlog = self.gl("glGetProgramInfoLog", None, U, I, C.POINTER(I), C.c_char_p)
        self.delete_program = self.gl("glDeleteProgram", None, U)

    def attrs(self, *values):
        return (self.I * len(values))(*values)

    def bind(self, name, restype, args):
        function = getattr(self.egl, name)
        function.restype, function.argtypes = restype, args
        return function

    def gl(self, name, restype, *args):
        address = self.getproc(name.encode())
        if not address:
            raise RuntimeError("Missing GLES function: " + name)
        return C.CFUNCTYPE(restype, *args)(address)

    def shader(self, text, kind):
        obj = self.create(kind)
        blob = text.encode()
        pointer, length = C.c_char_p(blob), self.I(len(blob))
        self.shader_source(obj, 1, C.byref(pointer), C.byref(length))
        self.compile(obj)
        ok, log_length = self.I(), self.I()
        self.shaderiv(obj, 0x8B81, C.byref(ok))
        self.shaderiv(obj, 0x8B84, C.byref(log_length))
        log = C.create_string_buffer(max(1, log_length.value))
        self.shaderlog(obj, len(log), None, log)
        return obj, {"compiled": bool(ok.value), "log": log.value.decode(), "sha256": sha(text)}

    def check(self, vertex, fragment):
        vs, vresult = self.shader(vertex, 0x8B31)
        fs, fresult = self.shader(fragment, 0x8B30)
        linked, message = False, ""
        try:
            if vresult["compiled"] and fresult["compiled"]:
                program = self.create_program()
                try:
                    self.attach(program, vs)
                    self.attach(program, fs)
                    self.link(program)
                    ok, log_length = self.I(), self.I()
                    self.programiv(program, 0x8B82, C.byref(ok))
                    self.programiv(program, 0x8B84, C.byref(log_length))
                    log = C.create_string_buffer(max(1, log_length.value))
                    self.programlog(program, len(log), None, log)
                    linked, message = bool(ok.value), log.value.decode()
                finally:
                    self.delete_program(program)
        finally:
            self.delete_shader(vs)
            self.delete_shader(fs)
        return {"vertex": vresult, "fragment": fresult, "linked": linked,
                "link_log": message, "passed": vresult["compiled"] and fresult["compiled"] and linked}

    def close(self):
        V, U = self.V, self.U
        self.makecurrent(self.display, None, None, None)
        self.bind("eglDestroySurface", U, [V, V])(self.display, self.surface)
        self.bind("eglDestroyContext", U, [V, V])(self.display, self.context)
        self.bind("eglTerminate", U, [V])(self.display)


class DesktopGL:
    """Desktop GLSL adaptation, distinct from WebGL/GLES validation."""
    kind = "desktop_glsl330_adapted"

    def __init__(self):
        self.context = create_context(require=330)

    def getstring(self, key):
        name = "GL_RENDERER" if key == 0x1F01 else "GL_VERSION"
        return str(self.context.info[name]).encode()

    def check(self, vertex, fragment):
        def adapt(source):
            source = re.sub(r"^#version[^\n]*", "#version 330", source)
            return desktop_identifiers(re.sub(r"^\s*precision\s+\w+\s+\w+\s*;", "", source, flags=re.M))
        try:
            program = self.context.program(vertex_shader=adapt(vertex), fragment_shader=adapt(fragment))
            program.release()
            return {"passed": True, "linked": True,
                    "adaptation": "ES version/precision and scalar noise3 identifier namespace; equations unchanged",
                    "vertex_sha256": sha(adapt(vertex)), "fragment_sha256": sha(adapt(fragment))}
        except Exception as error:
            return {"passed": False, "linked": False, "log": str(error)}

    def close(self):
        self.context.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", choices=["auto", "gles", "desktop"], default="auto")
    parser.add_argument("--player", type=Path, default=ROOT / "cloud-flight.html")
    parser.add_argument("--cinematic-webgl", type=Path, default=ROOT / "src/cinematic-webgl2.glsl")
    parser.add_argument("--output", type=Path, default=ROOT / "validation/player-verification.json")
    args = parser.parse_args()
    html = args.player.read_bytes().decode()
    script_match = re.search(r"<script>(.*?)</script>", html, re.S)
    if not script_match:
        raise ValueError("Player script is missing")
    script = script_match.group(1)
    scenes = json_constant(script, "SCENES")
    compact = json_constant(script, "COMPACT")
    vertex_match = re.search(r"const VERTEX=('[^\n]*');", script)
    if not vertex_match:
        raise ValueError("Vertex shader source is missing")
    vertex = ast.literal_eval(vertex_match.group(1))
    result = {
        "scope": "Exact original-source embedding and native GLES 3 compile/link of the actual HTML runtime strings; no drawing",
        "browser_runtime_tested": False, "html_sha256": sha(html),
        "compact_characters": len(compact), "compact_ascii": compact.isascii(),
        "compact_sha256": sha(compact),
        "compact_exact": compact == (ROOT / "src/erosion-flight.fragcoord.txt").read_bytes().decode(),
        "external_script_dependencies": bool(re.search(r"<script[^>]+src=", html)),
        "scenes": {},
    }
    with tempfile.TemporaryDirectory(prefix="cloud-player-check-") as directory:
        path = Path(directory) / "player.js"
        path.write_text(script)
        parsed = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True)
        result["javascript_parse_passed"] = parsed.returncode == 0
        result["javascript_parse_log"] = parsed.stderr
    if args.compiler == "desktop" or (args.compiler == "auto" and sys.platform != "linux"):
        compiler = DesktopGL()
    else:
        try:
            compiler = GLES()
        except (OSError, RuntimeError) as error:
            if args.compiler == "gles":
                raise
            result["gles_unavailable"] = str(error)
            compiler = DesktopGL()
    result["compiler_kind"] = getattr(compiler, "kind", "native_gles3")
    result["scope"] = "Exact embeddings and native shader compile/link; adapted desktop GLSL is not WebGL/GLES validation; no drawing"
    try:
        result["renderer"] = compiler.getstring(0x1F01).decode()
        result["gl_version"] = compiler.getstring(0x1F02).decode()
        for key, data in scenes.items():
            original = (ROOT / "src" / data["filename"]).read_bytes().decode().replace("\r\n", "\n")
            result["scenes"][key] = {"source_exact": original == data["source"],
                                     "source_sha256": sha(original),
                                     "runtime_sha256": sha(data["runtime"]),
                                     "native_shader": compiler.check(vertex, data["runtime"])}
            if key == "cinematic":
                standalone = args.cinematic_webgl.read_bytes().decode().replace("\r\n", "\n")
                result["scenes"][key]["standalone_webgl2_export_exact"] = standalone == data["runtime"]
                result["scenes"][key]["standalone_webgl2_sha256"] = sha(standalone)
                result["scenes"][key]["download_selects_runtime"] = data.get("download_runtime") is True and data.get("download_filename") == "cinematic-webgl2.glsl"
    finally:
        compiler.close()
    result["passed"] = all((result["compact_exact"], result["compact_ascii"],
                            result["compact_characters"] == 493,
                            result["javascript_parse_passed"],
                            not result["external_script_dependencies"],
                            result["scenes"]["cinematic"]["standalone_webgl2_export_exact"],
                            result["scenes"]["cinematic"]["download_selects_runtime"],
                            all(x["source_exact"] and x["native_shader"]["passed"] for x in result["scenes"].values())))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
