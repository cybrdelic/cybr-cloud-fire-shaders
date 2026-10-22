#!/usr/bin/env python3
"""Compile actual shader sources with Mesa OpenGL ES 3 via surfaceless EGL.

This intentionally reports its scope: GLES is not WebGL. A rejected old WebGL
struct ternary may compile here, which is precisely the previous testing gap.
"""
import argparse, ctypes as C, hashlib, json, os
from pathlib import Path

os.environ.setdefault('EGL_PLATFORM','surfaceless')
os.environ.setdefault('MESA_SHADER_CACHE_DIR','/tmp/fragcoord-mesa-cache')
V=C.c_void_p; I=C.c_int; U=C.c_uint
egl=C.CDLL('libEGL.so.1')
def bind(name,restype,args):
    f=getattr(egl,name);f.restype=restype;f.argtypes=args;return f
getproc=bind('eglGetProcAddress',V,[C.c_char_p])
error=bind('eglGetError',U,[])
getdisplay=C.CFUNCTYPE(V,U,V,C.POINTER(I))(getproc(b'eglGetPlatformDisplayEXT'))
initialize=bind('eglInitialize',U,[V,C.POINTER(I),C.POINTER(I)])
choose=bind('eglChooseConfig',U,[V,C.POINTER(I),C.POINTER(V),I,C.POINTER(I)])
bindapi=bind('eglBindAPI',U,[U])
createcontext=bind('eglCreateContext',V,[V,V,V,C.POINTER(I)])
createsurface=bind('eglCreatePbufferSurface',V,[V,V,C.POINTER(I)])
makecurrent=bind('eglMakeCurrent',U,[V,V,V,V])
def attrs(*values):return (I*len(values))(*values)
display=getdisplay(0x31DD,None,attrs(0x3038))
major,minor=I(),I();assert initialize(display,C.byref(major),C.byref(minor)),hex(error())
assert bindapi(0x30A0),hex(error())
config,count=V(),I()
assert choose(display,attrs(0x3033,1,0x3040,0x40,0x3024,8,0x3023,8,0x3022,8,0x3021,8,0x3038),C.byref(config),1,C.byref(count)) and count.value,hex(error())
context=createcontext(display,config,None,attrs(0x3098,3,0x3038));assert context,hex(error())
surface=createsurface(display,config,attrs(0x3057,16,0x3056,16,0x3038));assert surface,hex(error())
assert makecurrent(display,surface,surface,context),hex(error())
def gl(name,restype,*args):
    p=getproc(name.encode());assert p,name
    return C.CFUNCTYPE(restype,*args)(p)
getstring=gl('glGetString',C.c_char_p,U)
create=gl('glCreateShader',U,U)
source=gl('glShaderSource',None,U,I,C.POINTER(C.c_char_p),C.POINTER(I))
compile_=gl('glCompileShader',None,U)
shaderiv=gl('glGetShaderiv',None,U,U,C.POINTER(I))
shaderlog=gl('glGetShaderInfoLog',None,U,I,C.POINTER(I),C.c_char_p)
delete=gl('glDeleteShader',None,U)
createprogram=gl('glCreateProgram',U)
attach=gl('glAttachShader',None,U,U)
link=gl('glLinkProgram',None,U)
programiv=gl('glGetProgramiv',None,U,U,C.POINTER(I))
programlog=gl('glGetProgramInfoLog',None,U,I,C.POINTER(I),C.c_char_p)
deleteprogram=gl('glDeleteProgram',None,U)

def shader(text,kind):
    obj=create(kind);blob=text.encode();sp=C.c_char_p(blob);n=I(len(blob))
    source(obj,1,C.byref(sp),C.byref(n));compile_(obj)
    ok,length=I(),I();shaderiv(obj,0x8B81,C.byref(ok));shaderiv(obj,0x8B84,C.byref(length))
    buf=C.create_string_buffer(max(length.value,1));shaderlog(obj,len(buf),None,buf)
    return obj,{'compiled':bool(ok.value),'log':buf.value.decode(),'sha256':hashlib.sha256(blob).hexdigest()}

def main():
    from build_player import PREFIX,VERTEX
    ap=argparse.ArgumentParser(description='Compile/link one FragCoord GLSL pass using native OpenGL ES 3; not browser validation.')
    ap.add_argument('source',type=Path);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
    text=a.source.read_text()
    vs,vcheck=shader(VERTEX,0x8B31)
    fs,fcheck=shader(PREFIX+text,0x8B30)
    linked=False;log=''
    if vcheck['compiled'] and fcheck['compiled']:
        p=createprogram();attach(p,vs);attach(p,fs);link(p)
        ok,length=I(),I();programiv(p,0x8B82,C.byref(ok));programiv(p,0x8B84,C.byref(length))
        buf=C.create_string_buffer(max(length.value,1));programlog(p,len(buf),None,buf)
        linked=bool(ok.value);log=buf.value.decode();deleteprogram(p)
    delete(fs);delete(vs)
    result={'scope':'Native OpenGL ES 3 compiler/linker, not browser or ANGLE WebGL2 runtime validation',
            'source':str(a.source),'source_sha256':hashlib.sha256(text.encode()).hexdigest(),
            'renderer':getstring(0x1F01).decode(),'version':getstring(0x1F02).decode(),'shading_language':getstring(0x8B8C).decode(),
            'exact_player_prefix':True,'vertex':vcheck,'fragment':fcheck,'linked':linked,'link_log':log,
            'all_compiled_linked':bool(vcheck['compiled'] and fcheck['compiled'] and linked),
            'browser_runtime_tested':False}
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
    if not result['all_compiled_linked']:raise SystemExit(1)
if __name__=='__main__':main()
