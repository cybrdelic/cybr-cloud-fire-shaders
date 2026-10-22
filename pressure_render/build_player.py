#!/usr/bin/env python3
"""Package the exact FragCoord shader passes in a self-contained WebGL2 runner."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parent
sources={name:(ROOT/'fragcoord'/f'{name}.glsl').read_text() for name in ['common','simulation','shading','main']}
html='''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pressure fireball</title>
<style>
*{box-sizing:border-box}html,body{margin:0;height:100%;background:#111a23;color:#eef2f4;font:14px system-ui,sans-serif}canvas{width:100%;height:100%;display:block}#bar{position:fixed;left:24px;right:24px;bottom:22px;display:flex;align-items:center;gap:12px;padding:12px 16px;border-radius:12px;background:#101921da;backdrop-filter:blur(14px);border:1px solid #ffffff24}button,select{font:inherit;color:inherit;background:#ffffff12;border:1px solid #ffffff30;border-radius:7px;padding:8px 14px;cursor:pointer}button:hover{background:#ffffff26}.name{letter-spacing:.16em;font-size:11px;margin-right:auto}#message{position:fixed;top:30%;left:10%;right:10%;font-size:18px;line-height:1.6;text-align:center;white-space:pre-wrap}#message:empty{display:none}label{font-size:12px;display:flex;gap:8px;align-items:center}@media(max-width:600px){#bar{left:10px;right:10px;gap:7px;padding:10px}.name{display:none}button,select{padding:8px}}
</style>
<canvas id="canvas"></canvas><div id="message"></div>
<div id="bar"><span class="name">PRESSURE / FIRE</span><button id="pause">Pause</button><button id="restart">Restart</button></div>
<script>
const sources=__SOURCES__;
const canvas=document.getElementById('canvas'),message=document.getElementById('message');
const gl=canvas.getContext('webgl2',{alpha:false,antialias:false,preserveDrawingBuffer:false});
let failed=false;
function fail(e){failed=true;message.textContent=e.message||String(e);console.error(e);}
if(!gl)fail(new Error('This browser could not create WebGL2. Open this file in a browser with hardware graphics enabled.'));
if(gl&&!gl.getExtension('EXT_color_buffer_float'))fail(new Error('Floating-point render targets are required for this simulation.'));
if(!failed){
const vertex='#version 300 es\\nin vec2 position;void main(){gl_Position=vec4(position,0,1);}';
const prefix='#version 300 es\\nprecision highp float;precision highp int;precision highp sampler2D;uniform vec2 u_resolution;uniform float u_time,u_time_delta;uniform int u_frame,u_recursion,u_max_recursion;uniform sampler2D u_pass1,u_pass2;out vec4 fragColor;\\n';
function compile(type,source){const s=gl.createShader(type);gl.shaderSource(s,source);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(s));return s;}
function program(fragment){const p=gl.createProgram(),vs=compile(gl.VERTEX_SHADER,vertex),fs=compile(gl.FRAGMENT_SHADER,fragment);gl.attachShader(p,vs);gl.attachShader(p,fs);gl.linkProgram(p);gl.deleteShader(vs);gl.deleteShader(fs);if(!gl.getProgramParameter(p,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(p));const names=['u_resolution','u_time','u_frame','u_pass1','u_pass2'];const uniforms={};for(const n of names)uniforms[n]=gl.getUniformLocation(p,n);return {p,uniforms,position:gl.getAttribLocation(p,'position')};}
function target(w,h,half,linear){const t=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,t);gl.texImage2D(gl.TEXTURE_2D,0,half?gl.RGBA16F:gl.RGBA32F,w,h,0,gl.RGBA,half?gl.HALF_FLOAT:gl.FLOAT,null);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,linear?gl.LINEAR:gl.NEAREST);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,linear?gl.LINEAR:gl.NEAREST);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);const f=gl.createFramebuffer();gl.bindFramebuffer(gl.FRAMEBUFFER,f);gl.framebufferTexture2D(gl.FRAMEBUFFER,gl.COLOR_ATTACHMENT0,gl.TEXTURE_2D,t,0);if(gl.checkFramebufferStatus(gl.FRAMEBUFFER)!==gl.FRAMEBUFFER_COMPLETE)throw Error('A floating-point framebuffer could not be created.');gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT);return {t,f,w,h};}
const buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,3,-1,-1,3]),gl.STATIC_DRAW);
const END=4.775;
let programs={},states=[],lit=null,front=0,simFrame=0,simTime=0,accumulator=0,paused=false;
function draw(p,out,w,h,frame){gl.useProgram(p.p);gl.bindFramebuffer(gl.FRAMEBUFFER,out);gl.viewport(0,0,w,h);gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.enableVertexAttribArray(p.position);gl.vertexAttribPointer(p.position,2,gl.FLOAT,false,0,0);gl.uniform2f(p.uniforms.u_resolution,w,h);gl.uniform1i(p.uniforms.u_frame,frame);gl.uniform1f(p.uniforms.u_time,simTime);gl.uniform1i(p.uniforms.u_pass1,0);gl.uniform1i(p.uniforms.u_pass2,1);gl.drawArrays(gl.TRIANGLES,0,3);}
function simPass(frame){gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,states[front].t);const next=1-front;draw(programs.simulation,states[next].f,states[next].w,states[next].h,frame);front=next;}
function reset(){
 for(const t of states){gl.deleteTexture(t.t);gl.deleteFramebuffer(t.f);}if(lit){gl.deleteTexture(lit.t);gl.deleteFramebuffer(lit.f);}for(const p of Object.values(programs))gl.deleteProgram(p.p);
 const nx=48,ny=56,nz=48,tw=nx*8,th=ny*(nz/8);
 let common=sources.common.replace('ivec3(48,56,48)',`ivec3(${nx},${ny},${nz})`).replace('ivec2(384,336)',`ivec2(${tw},${th})`);
 programs={};for(const name of ['simulation','shading','main'])programs[name]=program(prefix+common+'\\n'+sources[name]);
 states=[target(tw*2+1,th*2,false,false),target(tw*2+1,th*2,false,false)];lit=target(tw,th,true,true);front=0;simFrame=0;simTime=0;accumulator=0;
 simPass(0);simFrame=1;
}
function display(){const dpr=Math.min(devicePixelRatio||1,1.5),w=Math.max(2,Math.round(innerWidth*dpr)),h=Math.max(2,Math.round(innerHeight*dpr));if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h;}gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,states[front].t);draw(programs.shading,lit.f,lit.w,lit.h,simFrame);gl.activeTexture(gl.TEXTURE1);gl.bindTexture(gl.TEXTURE_2D,lit.t);draw(programs.main,null,w,h,simFrame);}
let last=performance.now();
function frame(now){if(failed)return;try{const delta=Math.min((now-last)/1000,.1);last=now;if(!paused){accumulator=Math.min(accumulator+delta*.6,.1);let steps=0;while(accumulator>=.0025&&steps<20&&simTime<END-1e-8){simPass(simFrame);simPass(simFrame);simFrame++;simTime+=.0025;accumulator-=.0025;steps++;}if(simTime>=END-1e-8){paused=true;document.getElementById('pause').textContent='Replay';}}display();requestAnimationFrame(frame);}catch(e){fail(e);}}
document.getElementById('pause').onclick=()=>{try{if(simTime>=END-1e-8){reset();paused=false;}else paused=!paused;document.getElementById('pause').textContent=paused?'Play':'Pause';}catch(e){fail(e);}};
document.getElementById('restart').onclick=()=>{try{reset();paused=false;document.getElementById('pause').textContent='Pause';}catch(e){fail(e);}};
document.addEventListener('keydown',e=>{if(e.code==='Space'){e.preventDefault();document.getElementById('pause').click();}if(e.key.toLowerCase()==='r')document.getElementById('restart').click();});
canvas.addEventListener('webglcontextlost',e=>{e.preventDefault();fail(new Error('Graphics context lost. Reload this file to restart the simulation.'));});
try{reset();requestAnimationFrame(frame);}catch(e){fail(e);}
}
</script></html>
'''
html=html.replace('__SOURCES__',json.dumps(sources))
out=ROOT/'pressure-fireball.html';out.write_text(html)
print(out,len(html.encode()))
