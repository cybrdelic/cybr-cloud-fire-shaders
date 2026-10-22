#!/usr/bin/env python3
"""Build an offline, self-contained WebGL2 viewer from the exact cloud shader.

The HTML wrapper is deliberately outside the compact shader character budget.
No network calls, imports, external fonts, textures, or telemetry are generated.
"""
import argparse, hashlib, json, re
from pathlib import Path

PREFIX = '''#version 300 es
precision highp float;
precision highp int;
uniform vec2 u_resolution;
uniform float u_time;
uniform float u_time_delta;
uniform int u_frame;
out vec4 fragColor;
'''
VERTEX = '''#version 300 es
void main(){
    vec2 p=vec2(float((gl_VertexID<<1)&2),float(gl_VertexID&2));
    gl_Position=vec4(p*2.0-1.0,0.0,1.0);
}
'''

TEMPLATE = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="dark">
<title>Cloud Flight</title>
<style>
:root{font:14px/1.45 system-ui,sans-serif;color:#e9edf3;background:#10151d;color-scheme:dark}
*{box-sizing:border-box}body{margin:0;min-height:100svh;display:flex;flex-direction:column}
main{flex:1;min-height:0;display:grid;place-items:center;background:#080c12;padding:0}
.stage{position:relative;width:100%;max-width:177.778svh;aspect-ratio:16/9;background:#102030}
canvas{display:block;width:100%;height:100%;touch-action:pan-y}
#error{display:none;position:absolute;inset:0;overflow:auto;place-content:center;padding:24px;background:#111924eF;white-space:pre-wrap;font:13px/1.55 ui-monospace,monospace}
footer{padding:12px max(16px,env(safe-area-inset-right)) max(12px,env(safe-area-inset-bottom));background:#10151d}
.controls{display:flex;align-items:center;gap:10px;flex-wrap:wrap;max-width:1500px;margin:auto}
button,select{font:inherit;min-height:38px;border:1px solid #3b4656;border-radius:7px;color:inherit;background:#1a2431;padding:7px 12px;cursor:pointer}
button:hover,select:hover{background:#263448}button:focus-visible,select:focus-visible,input:focus-visible{outline:2px solid #9fcaff;outline-offset:3px}
button:disabled{opacity:.5;cursor:default}label{display:flex;align-items:center;gap:8px;color:#c2ccda}
.scrub{flex:1;min-width:140px;accent-color:#c1d9f7;height:30px;cursor:pointer}
.time{font-variant-numeric:tabular-nums;min-width:80px;color:#d7e2ef}
.meta{max-width:1500px;margin:8px auto 0;display:flex;gap:8px;flex-wrap:wrap;justify-content:space-between;color:#a2b0c1;font-size:12px}
summary{cursor:pointer;width:max-content;padding:6px 0;color:#c3d0e0}details{max-width:1500px;margin:5px auto 0}details p{color:#a2b0c1;margin:8px 0}
.source-actions{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0}textarea{display:block;width:100%;min-height:110px;padding:12px;resize:vertical;border:1px solid #344155;border-radius:7px;background:#0a111b;color:#dce7f6;font:12px/1.5 ui-monospace,monospace}
@media(max-width:600px){footer{padding-top:10px}.controls{gap:8px}.scrub{order:4;flex-basis:calc(100% - 90px)}.time{order:5}label{margin-left:auto;font-size:12px}select{max-width:145px}.meta{font-size:11px}}
</style>
</head>
<body>
<main><div class="stage"><canvas id="canvas" aria-label="Animated procedural clouds"></canvas><div id="error" role="alert"></div></div></main>
<footer>
<div class="controls">
<button id="pause" type="button">Pause</button>
<button id="restart" type="button">Restart</button>
<input id="scrub" class="scrub" type="range" min="0" max="10" step="0.001" value="0" aria-label="Animation time in seconds">
<output id="time" class="time" for="scrub">0.00 / 10 s</output>
<label>Quality <select id="quality"><option value="480">Fast · 480 px</option><option value="960">Balanced · 960 px</option><option value="1600">Detail · 1600 px</option></select></label>
</div>
<div class="meta"><span id="identity">Cloud Flight · __CHARS__-character FragCoord shader</span><span id="timing">Starting WebGL2…</span></div>
<details><summary>Shader source</summary>
<p>The complete compact shader is __CHARS__ characters. The viewer and expanded GLSL are outside that count. This player runs locally and makes no network requests.</p>
<textarea id="source" readonly spellcheck="false" aria-label="Complete compact FragCoord shader"></textarea>
<div class="source-actions"><button id="copy" type="button">Copy compact shader</button><button id="downloadCompact" type="button">Save compact shader</button><button id="downloadGLSL" type="button">Save GLSL</button></div>
</details>
</footer>
<script>
'use strict';
const compactSource=__COMPACT__;
const shaderSource=__GLSL__;
const fragmentPrefix=__PREFIX__;
const vertexSource=__VERTEX__;
const DURATION=10;
const el=id=>document.getElementById(id);
const canvas=el('canvas'),error=el('error'),pause=el('pause'),restart=el('restart'),scrub=el('scrub'),timeLabel=el('time'),quality=el('quality'),timing=el('timing');
el('source').value=compactSource;
quality.value=matchMedia('(pointer:coarse)').matches?'480':'960';
let gl=null,program=null,vao=null,uniforms={},frame=0,shaderTime=0,playing=true,lastClock=null,raf=0,pending=null,lost=false,failed=false,dirty=true;
let lastDraw=0,intervalEMA=0,intervalSamples=0,lastStats=0,lastDelta=0;
function failure(message){failed=true;error.textContent=message;error.style.display='grid';playing=false;pause.textContent='Play';timing.textContent='Playback stopped';cancelAnimationFrame(raf);raf=0;}
function compile(type,source){const s=gl.createShader(type);gl.shaderSource(s,source);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS)){const log=gl.getShaderInfoLog(s)||'Unknown shader compilation error';gl.deleteShader(s);throw new Error(log);}return s;}
function setup(){
 gl=canvas.getContext('webgl2',{alpha:false,antialias:false,depth:false,stencil:false,preserveDrawingBuffer:false,powerPreference:'high-performance'});
 if(!gl)throw new Error('WebGL2 is not available in this browser. Use the rendered MP4 to view this scene.');
 const vs=compile(gl.VERTEX_SHADER,vertexSource),fs=compile(gl.FRAGMENT_SHADER,fragmentPrefix+shaderSource);
 program=gl.createProgram();gl.attachShader(program,vs);gl.attachShader(program,fs);gl.linkProgram(program);gl.deleteShader(vs);gl.deleteShader(fs);
 if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw new Error(gl.getProgramInfoLog(program)||'Shader link failed');
 vao=gl.createVertexArray();gl.bindVertexArray(vao);gl.useProgram(program);
 for(const name of ['u_resolution','u_time','u_time_delta','u_frame'])uniforms[name]=gl.getUniformLocation(program,name);
 gl.disable(gl.DEPTH_TEST);gl.disable(gl.BLEND);gl.disable(gl.DITHER);gl.clearColor(0.05,0.1,0.2,1);pending=null;dirty=true;failed=false;error.style.display='none';
}
function resize(){
 const box=canvas.getBoundingClientRect(),pixelRatio=Math.min(devicePixelRatio||1,2),cap=Number(quality.value);
 const width=Math.max(2,Math.round(Math.min(cap,box.width*pixelRatio)/2)*2),height=Math.max(2,Math.round(width*box.height/Math.max(box.width,1)/2)*2);
 if(canvas.width!==width||canvas.height!==height){canvas.width=width;canvas.height=height;dirty=true;}
}
function syncControls(){scrub.value=String(shaderTime);timeLabel.textContent=shaderTime.toFixed(2)+' / 10 s';pause.textContent=playing?'Pause':'Play';}
function schedule(){if(!raf&&!document.hidden&&!lost)raf=requestAnimationFrame(tick);}
function tick(now){
 raf=0;if(document.hidden||lost)return;
 const elapsed=lastClock===null?0:Math.max(0,(now-lastClock)/1000);lastClock=now;
 if(playing){shaderTime=Math.min(DURATION,shaderTime+elapsed);dirty=true;lastDelta=elapsed;if(shaderTime>=DURATION)playing=false;}
 syncControls();resize();
 let gpuReady=true;
 if(pending){const state=gl.clientWaitSync(pending,0,0);gpuReady=state===gl.ALREADY_SIGNALED||state===gl.CONDITION_SATISFIED;if(state===gl.WAIT_FAILED){gl.deleteSync(pending);pending=null;failure('Graphics synchronization failed. Restart the player to retry.');return;}if(gpuReady){gl.deleteSync(pending);pending=null;}}
 if(dirty&&gpuReady){
  if(lastDraw&&playing){const ms=now-lastDraw;intervalEMA=intervalSamples?intervalEMA*.88+ms*.12:ms;intervalSamples++;}lastDraw=now;
  gl.viewport(0,0,canvas.width,canvas.height);gl.useProgram(program);gl.bindVertexArray(vao);
  gl.uniform2f(uniforms.u_resolution,canvas.width,canvas.height);gl.uniform1f(uniforms.u_time,shaderTime);gl.uniform1f(uniforms.u_time_delta,lastDelta);gl.uniform1i(uniforms.u_frame,frame++);
  gl.drawArrays(gl.TRIANGLES,0,3);pending=gl.fenceSync(gl.SYNC_GPU_COMMANDS_COMPLETE,0);gl.flush();dirty=false;
 }
 if(now-lastStats>250){const rate=intervalSamples>0?(1000/intervalEMA).toFixed(1)+' fps · '+intervalEMA.toFixed(1)+' ms/frame':'measuring';timing.textContent=canvas.width+' × '+canvas.height+' · '+(playing?rate:'paused');lastStats=now;}
 if(playing||dirty||pending)schedule();
}
pause.addEventListener('click',()=>{if(lost||failed)return;playing=!playing;if(playing&&shaderTime>=DURATION){shaderTime=0;frame=0;}lastClock=null;lastDraw=0;dirty=true;syncControls();schedule();});
restart.addEventListener('click',()=>{if(lost||failed){location.reload();return;}shaderTime=0;frame=0;playing=true;lastClock=null;lastDraw=0;intervalSamples=0;intervalEMA=0;dirty=true;syncControls();schedule();});
scrub.addEventListener('input',()=>{shaderTime=Number(scrub.value);playing=false;lastClock=null;lastDraw=0;lastDelta=0;dirty=true;syncControls();schedule();});
quality.addEventListener('change',()=>{dirty=true;lastDraw=0;intervalSamples=0;schedule();});
addEventListener('resize',()=>{dirty=true;schedule();});
document.addEventListener('visibilitychange',()=>{lastClock=null;lastDraw=0;if(document.hidden){cancelAnimationFrame(raf);raf=0;}else{dirty=true;schedule();}});
canvas.addEventListener('webglcontextlost',event=>{event.preventDefault();lost=true;failure('The graphics context was lost. Restart to reload the player, or wait for the browser to restore it.');});
canvas.addEventListener('webglcontextrestored',()=>{lost=false;try{setup();lastClock=null;lastDraw=0;playing=false;dirty=true;syncControls();schedule();}catch(e){failure(e.message);}});
function download(name,text){const url=URL.createObjectURL(new Blob([text],{type:'text/plain;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
el('downloadCompact').addEventListener('click',()=>download('cloud-flight-compact.txt',compactSource));
el('downloadGLSL').addEventListener('click',()=>download('cloud-flight.glsl',shaderSource));
el('copy').addEventListener('click',async()=>{try{await navigator.clipboard.writeText(compactSource);el('copy').textContent='Copied';}catch{const field=el('source');field.focus();field.select();el('copy').textContent='Select and copy';}setTimeout(()=>el('copy').textContent='Copy compact shader',1800);});
try{setup();syncControls();schedule();}catch(e){failure(e.message);}
</script>
</body>
</html>
'''

def js(value):
    return json.dumps(value,ensure_ascii=True).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('glsl',type=Path);parser.add_argument('compact',type=Path);parser.add_argument('output',type=Path)
    args=parser.parse_args();glsl=args.glsl.read_text();compact=args.compact.read_text()
    if re.search(r'^\s*#version',glsl,re.M):raise SystemExit('Input must be FragCoord GLSL without its own #version preamble')
    if 'void main(' not in glsl and 'void main (' not in glsl:raise SystemExit('Input must contain void main()')
    if len(compact)>=500:raise SystemExit(f'Compact shader is {len(compact)} characters; this build requires fewer than 500')
    values={'__CHARS__':str(len(compact)),'__COMPACT__':js(compact),'__GLSL__':js(glsl),'__PREFIX__':js(PREFIX),'__VERTEX__':js(VERTEX)}
    html=TEMPLATE
    for key,value in values.items():html=html.replace(key,value)
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(html)
    for key,expected in [('compactSource',compact),('shaderSource',glsl),('fragmentPrefix',PREFIX),('vertexSource',VERTEX)]:
        match=re.search(r'const '+key+r'=("(?:[^"\\]|\\.)*");',html)
        if not match or json.loads(match.group(1))!=expected:raise AssertionError('Embedded source changed: '+key)
    audit={'compact_characters':len(compact),'compact_ascii':compact.isascii(),'compact_source_sha256':hashlib.sha256(compact.encode()).hexdigest(),'glsl_source_sha256':hashlib.sha256(glsl.encode()).hexdigest(),'html_sha256':hashlib.sha256(html.encode()).hexdigest(),'exact_embedded_source':True,'browser_runtime_tested':False,'duration_shader_seconds':10,'html_wrapper_excluded_from_compact_count':True,'external_dependencies':[],'resolution_caps':[480,960,1600],'hidden_page_clock_paused':True,'frame_timing':'Wall-clock interval between render submissions, GPU fenced; not a GPU timer query.'}
    args.output.with_suffix('.build.json').write_text(json.dumps(audit,indent=2)+'\n');print(json.dumps(audit,indent=2))
if __name__=='__main__':main()
