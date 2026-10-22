#!/usr/bin/env python3
"""Build an offline, dependency-free WebGL2 player from the delivered sources.

The original GLSL strings are embedded with canonical LF newlines. The runtime copy gets
an ES 3.00 preamble where needed; that adaptation is recorded in the manifest.
The cinematic download is that complete runtime, also written to a GLSL file.
This wrapper is not part of the compact FragCoord character count.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re


PROJECT = Path(__file__).resolve().parents[1]


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def read_source(path: Path) -> str:
    """Git may check text out as CRLF on Windows; keep generated payloads portable."""
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


def fragment_for_webgl(source: str) -> str:
    """Supply standard uniforms only when referenced and not already declared."""
    body = re.sub(r"(?m)^\s*#version[^\n]*\n?", "", source, count=1)
    preamble = ["#version 300 es", "precision highp float;", "precision highp int;"]
    declarations = {
        "u_resolution": "vec2", "iResolution": "vec3",
        "u_time": "float", "iTime": "float",
        "u_time_delta": "float", "iTimeDelta": "float",
        "u_frame": "int", "iFrame": "int",
    }
    for name, glsl_type in declarations.items():
        if re.search(rf"\b{re.escape(name)}\b", body) and not re.search(
            rf"\buniform\s+(?:(?:highp|mediump|lowp)\s+)?\w+\s+{re.escape(name)}\b", body
        ):
            preamble.append(f"uniform {glsl_type} {name};")
    if re.search(r"\bgl_FragColor\b", body):
        body = re.sub(r"\bgl_FragColor\b", "fragColor", body)
    has_main = bool(re.search(r"\bvoid\s+main\s*\(", body))
    if not has_main and re.search(r"\bvoid\s+mainImage\s*\(", body):
        preamble.append("out vec4 oaiFragColor;")
        body += "\nvoid main(){mainImage(oaiFragColor,gl_FragCoord.xy);}\n"
    if has_main and re.search(r"\bfragColor\b", body) and not re.search(
        r"(?m)^\s*(?:layout\s*\([^\n]*\)\s*)?out\s+(?:(?:highp|mediump|lowp)\s+)?vec4\s+fragColor\s*;", body
    ):
        preamble.append("out vec4 fragColor;")
    if not re.search(r"\bvoid\s+main\s*\(", body):
        raise ValueError("Shader must provide void main() or void mainImage().")
    return "\n".join(preamble) + "\n#line 1\n" + body


HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="dark">
<title>Cloud flight</title>
<style>
:root{color-scheme:dark;font:14px/1.45 ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#e6ebf0;background:#0c1118;--muted:#98a5b3;--line:#2a3440;--focus:#bfd9ee}
*{box-sizing:border-box}[hidden]{display:none!important}body{margin:0;min-height:100svh;display:flex;flex-direction:column}button,select,input,a{-webkit-tap-highlight-color:transparent}button,select{font:inherit;color:inherit}button,a,select{touch-action:manipulation}button{cursor:pointer}a{color:inherit;text-decoration:none}button:focus-visible,select:focus-visible,input:focus-visible,a:focus-visible,summary:focus-visible{outline:2px solid var(--focus);outline-offset:4px}
header{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:18px max(22px,env(safe-area-inset-right)) 17px max(22px,env(safe-area-inset-left));border-bottom:1px solid var(--line)}.wordmark{font-size:11px;letter-spacing:.15em;color:var(--muted);white-space:nowrap}h1{font-size:17px;line-height:1.3;font-weight:500;margin:4px 0 0;letter-spacing:-.015em}.scene-picker{display:flex;gap:8px;align-items:center}.scene-picker label{font-size:12px;color:var(--muted)}select{max-width:100%;border:1px solid var(--line);border-radius:5px;background:#141d28;padding:8px 26px 8px 10px;min-height:38px}
main{flex:1;min-height:0;display:grid;place-items:center;background:#070b10}.stage{position:relative;width:100%;max-width:calc((100svh - 210px)*1.7777778);aspect-ratio:16/9;background:#101d2b;overflow:hidden}canvas{display:block;width:100%;height:100%}.stage-status{position:absolute;left:18px;bottom:14px;padding:5px 8px;border-radius:3px;color:#d7e2ec;background:#0b111bb3;font-size:11px;letter-spacing:.02em;pointer-events:none}.error{position:absolute;inset:0;background:#101822f5;display:none;align-content:center;padding:clamp(16px,4vw,48px);overflow:auto}.error.visible{display:grid}.error h2{font-size:18px;font-weight:500;margin:0 0 8px}.error p{color:#b7c5d2;max-width:620px;margin:0 0 12px}.error pre{padding:12px;border:1px solid #42505f;white-space:pre-wrap;overflow-wrap:anywhere;font:12px/1.5 ui-monospace,monospace;max-height:35svh;overflow:auto;margin:0}.error a{text-decoration:underline;text-underline-offset:3px}
footer{border-top:1px solid var(--line);padding:16px max(22px,env(safe-area-inset-right)) max(16px,env(safe-area-inset-bottom)) max(22px,env(safe-area-inset-left))}.controls{max-width:1440px;margin:0 auto;display:flex;align-items:center;gap:12px}.button{display:inline-flex;justify-content:center;align-items:center;gap:7px;min-height:38px;padding:8px 12px;border:1px solid var(--line);border-radius:5px;background:#172230;white-space:nowrap}.button:hover{background:#243242}.button.primary{background:#dce8f2;color:#142231;border-color:#dce8f2;min-width:84px}.button.primary:hover{background:#f1f6fa}.button:disabled{cursor:default;opacity:.45}.button svg{width:13px;height:13px}.timeline{display:flex;align-items:center;gap:12px;flex:1;min-width:120px}input[type=range]{width:100%;margin:0;accent-color:#d5e5f2;height:32px;cursor:pointer}.clock{white-space:nowrap;font-variant-numeric:tabular-nums;font-size:12px;color:#c0ccd8;min-width:80px}.quality{display:flex;gap:8px;align-items:center;color:var(--muted);font-size:12px}.quality select{min-height:34px;padding-top:6px;padding-bottom:6px}.subline{max-width:1440px;display:flex;align-items:center;justify-content:space-between;gap:12px;margin:12px auto 0;font-size:11px;color:var(--muted)}#videoLink{text-decoration:underline;text-underline-offset:3px}.source{max-width:1440px;margin:10px auto 0;border-top:1px solid var(--line);padding-top:7px}summary{cursor:pointer;font-size:12px;color:#aab7c5;width:max-content;padding:4px 0}.source-content{padding:8px 0 0}.source-content p{font-size:12px;color:var(--muted);max-width:820px;margin:0 0 10px}.source-actions{display:flex;gap:8px;flex-wrap:wrap}.source-actions .button{font-size:12px;min-height:34px}.source textarea{display:block;width:100%;min-height:95px;max-height:260px;resize:vertical;margin:10px 0 0;border:1px solid var(--line);border-radius:4px;padding:12px;background:#090f17;color:#d8e2ec;font:12px/1.55 ui-monospace,monospace}.visually-hidden{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%)}
@media(max-width:700px){header{padding:14px 14px 13px;gap:10px}.wordmark{font-size:10px}h1{font-size:15px}.scene-picker label{display:none}.scene-picker select{font-size:12px;max-width:170px}.stage{max-width:none}footer{padding:13px 14px max(14px,env(safe-area-inset-bottom))}.controls{flex-wrap:wrap;gap:9px}.button{min-height:40px}.timeline{order:3;flex-basis:100%}.quality{margin-left:auto}.quality label{display:none}.clock{font-size:11px}.subline{align-items:baseline;font-size:10px}.stage-status{left:10px;bottom:10px;font-size:10px}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto}}
</style>
</head>
<body>
<header><div><div class="wordmark">CYBR / ATMOSPHERE</div><h1 id="heading">Cinematic flight</h1></div><div class="scene-picker"><label for="scene">Scene</label><select id="scene"><option value="cinematic">Cinematic flight</option><option value="erosion">Erosion flight · 493 chars</option></select></div></header>
<main><div class="stage"><canvas id="canvas" aria-label="Procedural cloud flight preview"></canvas><span class="stage-status" id="stageStatus" aria-live="polite">Preparing preview</span><div id="error" class="error" role="alert"><h2>Preview unavailable</h2><p id="errorSummary"></p><pre id="errorLog"></pre></div></div></main>
<footer>
<div class="controls"><button id="play" class="button primary" type="button">Play</button><button id="restart" class="button" type="button" aria-label="Restart the ten-second flight">Restart</button><div class="timeline"><label class="visually-hidden" for="scrub">Time in seconds</label><input id="scrub" type="range" min="0" max="10" step="0.001" value="0"><output id="clock" class="clock" for="scrub">0.00 / 10 s</output></div><div class="quality"><label for="quality">Preview</label><select id="quality"><option value="auto">Auto</option><option value="160">160 px</option><option value="240">240 px</option><option value="320">320 px</option><option value="480">480 px</option><option value="640">640 px</option><option value="960">960 px</option></select></div></div>
<div class="subline"><span id="status">Local shader preview</span><a id="videoLink" href="cinematic-cloud-flight.mp4" download>Download 10-second video</a></div>
<details class="source"><summary>Source &amp; downloads</summary><div class="source-content"><p id="sourceNote">The shader runs locally. Preview speed depends on your device. The rendered videos use a separate offline rendering path.</p><div class="source-actions"><button id="downloadGLSL" class="button" type="button">Download GLSL</button><button id="downloadCompact" class="button" type="button">Download 493-character source</button><button id="copyCompact" class="button" type="button">Copy compact source</button></div><textarea id="source" readonly spellcheck="false" aria-label="Exact compact FragCoord source"></textarea></div></details>
</footer>
<script>
'use strict';
const SCENES=__SCENES__;
const COMPACT=__COMPACT__;
const DURATION=10;
const VERTEX='#version 300 es\nvoid main(){vec2 p=vec2(float((gl_VertexID<<1)&2),float(gl_VertexID&2));gl_Position=vec4(p*2.0-1.0,0.0,1.0);}';
const $=id=>document.getElementById(id);
const canvas=$('canvas'),playButton=$('play'),scrub=$('scrub'),clock=$('clock'),scenePicker=$('scene'),qualityPicker=$('quality');
const programs=new Map();
let gl=null,vao=null,active=null,pending=null,raf=0,playing=false,lost=false,failed=false,dirty=true;
let logicalTime=0,displayedTime=0,lastClock=null,frame=0,lastDelta=0,autoCap=matchMedia('(pointer:coarse)').matches?240:320;
let lastSubmit=0,submittedTime=0,submissionStart=0,completedFrames=0,emaFrameMs=0;
let sceneKey='cinematic';
let sceneGeneration=0,lastCompleted=null;
window.getCloudPreviewDiagnostics=()=>({scene:sceneKey,generation:sceneGeneration,completedFrames,lastCompleted:lastCompleted?{...lastCompleted}:null,pending:!!pending,failed,lost});
$('source').value=COMPACT;
function error(summary,details){failed=true;playing=false;playButton.textContent='Play';$('errorSummary').textContent=summary;$('errorLog').textContent=details||'';$('error').classList.add('visible');$('stageStatus').textContent='Preview stopped';$('status').textContent='The rendered videos remain available.';if(raf)cancelAnimationFrame(raf);raf=0;}
function compile(type,source){const shader=gl.createShader(type);gl.shaderSource(shader,source);gl.compileShader(shader);if(!gl.getShaderParameter(shader,gl.COMPILE_STATUS)){const message=gl.getShaderInfoLog(shader)||'No compiler log returned.';gl.deleteShader(shader);throw new Error(message);}return shader;}
function makeProgram(key){const source=SCENES[key];let vertex=null,fragment=null,program=null;try{vertex=compile(gl.VERTEX_SHADER,VERTEX);fragment=compile(gl.FRAGMENT_SHADER,source.runtime);program=gl.createProgram();gl.attachShader(program,vertex);gl.attachShader(program,fragment);gl.linkProgram(program);if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw new Error(gl.getProgramInfoLog(program)||'Program linking failed.');const uniforms={};for(let i=0;i<gl.getProgramParameter(program,gl.ACTIVE_UNIFORMS);i++){const info=gl.getActiveUniform(program,i);uniforms[info.name]={location:gl.getUniformLocation(program,info.name),type:info.type};}return {program,uniforms};}catch(e){if(program)gl.deleteProgram(program);throw e;}finally{if(vertex)gl.deleteShader(vertex);if(fragment)gl.deleteShader(fragment);}}
function setup(){gl=canvas.getContext('webgl2',{alpha:false,antialias:false,depth:false,stencil:false,preserveDrawingBuffer:false,powerPreference:'high-performance'});if(!gl)throw new Error('This browser did not provide a WebGL2 context.');vao=gl.createVertexArray();gl.bindVertexArray(vao);gl.disable(gl.BLEND);gl.disable(gl.DEPTH_TEST);gl.disable(gl.DITHER);gl.clearColor(.04,.08,.13,1);programs.clear();pending=null;activate(sceneKey);}
function activate(key){
 sceneKey=key;sceneGeneration++;completedFrames=0;lastCompleted=null;
 // Retiring the old fence does not cancel GPU work, but it prevents attributing
 // that work to the newly selected scene. Only the new scene's fence can count.
 if(pending){gl.deleteSync(pending.sync);pending=null;}
 $('stageStatus').textContent='Preparing '+SCENES[key].label;
 const scene=SCENES[key];$('heading').textContent=scene.label;$('videoLink').href=scene.video;$('videoLink').hidden=!scene.video;canvas.setAttribute('aria-label',scene.label+' procedural cloud preview');$('downloadCompact').hidden=key!=='erosion';$('copyCompact').hidden=key!=='erosion';$('source').hidden=key!=='erosion';$('sourceNote').textContent=key==='erosion'?'The complete compact FragCoord source is '+COMPACT.length+' ASCII characters. Expanded GLSL and this viewer are separate. The preview runs locally; playback speed depends on your device.':'This scene uses the full cinematic GLSL source. The preview runs locally; playback speed depends on your device. The rendered video uses a separate offline rendering path.';try{if(!programs.has(key))programs.set(key,makeProgram(key));active=programs.get(key);failed=false;$('error').classList.remove('visible');dirty=true;logicalTime=0;displayedTime=0;frame=0;lastClock=null;lastSubmit=0;emaFrameMs=0;playing=false;sync();schedule();}catch(e){error('The '+scene.label.toLowerCase()+' shader could not compile in this browser. The compiler details are below.',e.message);}
}
function sync(){playButton.textContent=playing?'Pause':'Play';scrub.value=String(logicalTime);clock.textContent=logicalTime.toFixed(2)+' / 10 s';}
function resize(){const box=canvas.getBoundingClientRect();const cap=qualityPicker.value==='auto'?autoCap:Number(qualityPicker.value);const width=Math.max(2,Math.round(Math.min(cap,Math.max(2,box.width)*Math.min(devicePixelRatio||1,2))/2)*2);const height=Math.max(2,Math.round(width*9/16));if(canvas.width!==width||canvas.height!==height){canvas.width=width;canvas.height=height;dirty=true;}}
function schedule(){if(!raf&&!lost&&!failed&&!document.hidden)raf=requestAnimationFrame(tick);}
function setUniforms(t,dt){for(const [name,u] of Object.entries(active.uniforms)){if(name==='u_resolution'||name==='iResolution'){if(u.type===gl.FLOAT_VEC3)gl.uniform3f(u.location,canvas.width,canvas.height,1);else gl.uniform2f(u.location,canvas.width,canvas.height);}else if(name==='u_time'||name==='iTime')gl.uniform1f(u.location,t);else if(name==='u_time_delta'||name==='iTimeDelta')gl.uniform1f(u.location,dt);else if(name==='u_frame'||name==='iFrame')gl.uniform1i(u.location,frame);}}
function completePending(now){
 if(!pending)return true;
 const submitted=pending;
 const result=gl.clientWaitSync(submitted.sync,0,0);
 if(result===gl.WAIT_FAILED){gl.deleteSync(submitted.sync);pending=null;error('The browser could not complete a graphics frame. Try a lower preview resolution or use the rendered video.','WebGL synchronization returned WAIT_FAILED.');return false;}
 if(result!==gl.ALREADY_SIGNALED&&result!==gl.CONDITION_SATISFIED){
  if(now-submitted.started>10000){gl.deleteSync(submitted.sync);pending=null;error('This GPU did not finish a frame within 10 seconds. Restart or use the rendered video.','Frame time limit reached; no further frames will be submitted.');}
  return false;
 }
 gl.deleteSync(submitted.sync);pending=null;
 if(submitted.generation!==sceneGeneration||submitted.scene!==sceneKey)return true;
 displayedTime=submitted.time;const elapsed=now-submitted.started;
 emaFrameMs=completedFrames?emaFrameMs*.8+elapsed*.2:elapsed;completedFrames++;
 lastCompleted={scene:submitted.scene,generation:submitted.generation,frame:submitted.frame,time:submitted.time,width:submitted.width,height:submitted.height};
 if(qualityPicker.value==='auto'&&elapsed>180&&autoCap>160){autoCap=Math.max(160,Math.floor(autoCap*.75/16)*16);dirty=true;}
 return true;
}
function tick(now){
 raf=0;if(lost||failed||document.hidden)return;
 const ready=completePending(now);if(failed)return;
 if(ready){
  resize();
  if(playing||dirty){
   if(playing){const elapsed=lastClock===null?0:Math.max(0,(now-lastClock)/1000);lastDelta=Math.min(elapsed,1/24);logicalTime=Math.min(DURATION,logicalTime+lastDelta);if(logicalTime>=DURATION)playing=false;}
   sync();
   gl.viewport(0,0,canvas.width,canvas.height);gl.useProgram(active.program);gl.bindVertexArray(vao);setUniforms(logicalTime,lastDelta);gl.drawArrays(gl.TRIANGLES,0,3);pending={sync:gl.fenceSync(gl.SYNC_GPU_COMMANDS_COMPLETE,0),scene:sceneKey,generation:sceneGeneration,frame,time:logicalTime,width:canvas.width,height:canvas.height,started:now};gl.flush();submissionStart=now;submittedTime=logicalTime;lastSubmit=now;lastClock=now;frame++;dirty=false;
  }
 }
 sync();const size=canvas.width+' × '+canvas.height;$('stageStatus').textContent=pending?'Rendering '+submittedTime.toFixed(2)+' s':(playing?'Playing':'Paused')+' · '+displayedTime.toFixed(2)+' s';$('status').textContent=size+' preview'+(emaFrameMs>0?' · '+Math.round(emaFrameMs)+' ms frame-time estimate':'')+(qualityPicker.value==='auto'?' · auto resolution':'');if(playing||dirty||pending)schedule();
}
playButton.addEventListener('click',()=>{if(failed||lost)return;const nextPlaying=!playing;if(nextPlaying&&logicalTime>=DURATION){logicalTime=0;frame=0;}playing=nextPlaying;lastClock=null;if(playing)dirty=true;sync();schedule();});
$('restart').addEventListener('click',()=>{if(failed||lost){location.reload();return;}logicalTime=0;displayedTime=0;frame=0;playing=true;lastClock=null;dirty=true;sync();schedule();});
scrub.addEventListener('input',()=>{logicalTime=Number(scrub.value);playing=false;lastClock=null;lastDelta=0;dirty=true;sync();schedule();});
scenePicker.addEventListener('change',()=>{if(lost)return;activate(scenePicker.value);});
qualityPicker.addEventListener('change',()=>{dirty=true;completedFrames=0;emaFrameMs=0;schedule();});
addEventListener('resize',()=>{dirty=true;schedule();});
document.addEventListener('visibilitychange',()=>{lastClock=null;if(document.hidden){if(raf)cancelAnimationFrame(raf);raf=0;}else{dirty=true;schedule();}});
canvas.addEventListener('webglcontextlost',event=>{event.preventDefault();lost=true;error('The browser released the graphics context. Restart to try again, or use the rendered video.','WebGL context lost.');});
canvas.addEventListener('webglcontextrestored',()=>{lost=false;failed=false;playing=false;lastClock=null;try{setup();}catch(e){error('The graphics context was restored, but the preview could not restart.',e.message);}});
function download(name,text,type='text/plain;charset=utf-8'){const url=URL.createObjectURL(new Blob([text],{type}));const link=document.createElement('a');link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
$('downloadGLSL').addEventListener('click',()=>{const scene=SCENES[sceneKey];download(scene.download_filename||scene.filename,scene.download_runtime?scene.runtime:scene.source);});
$('downloadCompact').addEventListener('click',()=>download('erosion-flight-'+COMPACT.length+'.fragcoord.txt',COMPACT));
$('copyCompact').addEventListener('click',async()=>{const button=$('copyCompact');try{await navigator.clipboard.writeText(COMPACT);button.textContent='Copied';}catch{const source=$('source');source.hidden=false;source.focus();source.select();button.textContent='Select and copy';}setTimeout(()=>{button.textContent='Copy compact source';},1800);});
try{setup();}catch(e){error('A WebGL2 preview could not be initialized. Use either rendered video to view the full flight.',e.message);}
</script>
</body>
</html>
'''


def safe_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":")).replace("<", "\\u003c")


def build(args: argparse.Namespace) -> dict:
    cinematic = read_source(args.cinematic)
    erosion = read_source(args.erosion)
    compact = read_source(args.compact)
    if not compact.isascii():
        raise ValueError("The compact FragCoord source must be ASCII.")
    if args.expected_compact_chars and len(compact) != args.expected_compact_chars:
        raise ValueError(f"Compact source has {len(compact)} characters; expected {args.expected_compact_chars}.")
    scenes = {
        "cinematic": {
            "label": "Cinematic flight", "filename": "cinematic.glsl",
            "source": cinematic, "runtime": fragment_for_webgl(cinematic),
            "download_filename": "cinematic-webgl2.glsl", "download_runtime": True,
            "video": "cinematic-cloud-flight.mp4" if not args.no_video_links else None,
        },
        "erosion": {
            "label": "Erosion flight", "filename": "erosion-flight.glsl",
            "source": erosion, "runtime": fragment_for_webgl(erosion),
            "video": f"erosion-flight-{len(compact)}.mp4" if not args.no_video_links else None,
        },
    }
    page = HTML.replace("__SCENES__", safe_json(scenes)).replace("__COMPACT__", safe_json(compact))
    page = page.replace("493 chars", f"{len(compact)} chars").replace("493-character source", f"{len(compact)}-character source")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(page, encoding="utf-8", newline="\n")
    cinematic_webgl_output = args.cinematic_webgl_output or args.output.parent / "src/cinematic-webgl2.glsl"
    cinematic_webgl_output.parent.mkdir(parents=True, exist_ok=True)
    cinematic_webgl_output.write_bytes(scenes["cinematic"]["runtime"].encode("utf-8"))
    result = {
        "output": args.output.name,
        "html_sha256": digest(page),
        "compact_characters": len(compact),
        "compact_ascii": True,
        "compact_sha256": digest(compact),
        "duration_seconds": 10,
        "default_playback": "paused; a single initial frame is requested",
        "preview_clock": "Advances only when ready to submit; at most 1/24 second per draw. Slow rendering stretches wall-clock playback.",
        "auto_preview_start_width": {"desktop": 320, "coarse_pointer": 240},
        "auto_preview_minimum_width": 160,
        "external_network_dependencies": [],
        "video_links_are_relative_sibling_files": not args.no_video_links,
        "exact_original_glsl_embedding": True,
        "source_line_endings": "LF; CRLF checkout newlines normalized without changing source text",
        "glsl_downloads": {
            "cinematic": {"filename": "cinematic-webgl2.glsl", "content": "exact compiled WebGL2 runtime", "sha256": digest(scenes["cinematic"]["runtime"])},
            "erosion": {"filename": "erosion-flight.glsl", "content": "exact expanded GLSL input", "sha256": digest(erosion)},
        },
        "cinematic_webgl_output": "src/" + cinematic_webgl_output.name,
        "wrapper_excluded_from_compact_count": True,
        "browser_runtime_tested": False,
        "provenance": "New continuation built from recovered V16 source and the documented V17 design; not resumed original V17 frames.",
        "sources": {
            key: {"sha256": digest(scene["source"]), "webgl_sha256": digest(scene["runtime"]),
                  "characters": len(scene["source"]), "webgl_adaptation": "ES 3.00 version and precision; missing referenced standard uniforms/output supplied"}
            for key, scene in scenes.items()
        },
    }
    args.output.with_suffix(".build.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cinematic", type=Path, default=PROJECT / "src/cinematic.glsl")
    parser.add_argument("--erosion", type=Path, default=PROJECT / "src/erosion-flight.glsl")
    parser.add_argument("--compact", type=Path, default=PROJECT / "src/erosion-flight.fragcoord.txt")
    parser.add_argument("--expected-compact-chars", type=int, default=493)
    parser.add_argument("--output", type=Path, default=PROJECT / "cloud-flight.html")
    parser.add_argument("--cinematic-webgl-output", type=Path, help="Complete cinematic runtime export; defaults to OUTPUT_DIRECTORY/src/cinematic-webgl2.glsl")
    parser.add_argument("--no-video-links", action="store_true")
    print(json.dumps(build(parser.parse_args()), indent=2))


if __name__ == "__main__":
    main()
