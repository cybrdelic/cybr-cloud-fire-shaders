#!/usr/bin/env node
'use strict';
// Independent syntax/source check; this does not run a browser or WebGL.
const fs=require('fs'),path=require('path'),vm=require('vm'),crypto=require('crypto');
const htmlPath=process.argv[2];
if(!htmlPath)throw new Error('Usage: node audit_player.cjs path/to/cloud-flight.html');
const dir=path.dirname(htmlPath),html=fs.readFileSync(htmlPath,'utf8');
const scripts=[...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
if(scripts.length!==1)throw new Error('Expected exactly one inline script');
new vm.Script(scripts[0][1],{filename:htmlPath});
const field=name=>{
 const match=html.match(new RegExp('const '+name+'=("(?:[^"\\\\]|\\\\.)*");'));
 if(!match)throw new Error('Missing embedded value: '+name);
 return JSON.parse(match[1]);
};
const compact=field('compactSource'),glsl=field('shaderSource'),prefix=field('fragmentPrefix'),vertex=field('vertexSource');
const equal=(got,want,label)=>{if(got!==want)throw new Error(label+' mismatch');};
const hash=value=>crypto.createHash('sha256').update(value).digest('hex');
equal(compact,fs.readFileSync(path.join(dir,'cloud-flight.fragcoord.txt'),'utf8'),'Compact source');
equal(glsl,fs.readFileSync(path.join(dir,'cloud-flight.glsl'),'utf8'),'Expanded GLSL');
if(compact.length>=500)throw new Error('Compact source must be fewer than 500 characters');
if(!/const DURATION=10;/.test(html))throw new Error('Expected 10-second playback duration');
const link=JSON.parse(fs.readFileSync(path.join(dir,'cloud-flight-link.json'),'utf8'));
equal(hash(compact),link.source_sha256,'Link compact hash');
equal(hash(glsl),link.glsl_sha256,'Link GLSL hash');
const code=new URL(link.url).hash.match(/^#code=(.*)$/);
if(!code)throw new Error('Unexpected FragCoord link format');
equal(Buffer.from(code[1],'base64url').toString('utf8'),compact,'Link source roundtrip');
const gles=JSON.parse(fs.readFileSync(path.join(dir,'cloud-gles-validation.json'),'utf8'));
if(!gles.all_compiled_linked)throw new Error('GLES compile/link failed');
equal(hash(glsl),gles.source_sha256,'GLES source hash');
equal(hash(prefix+glsl),gles.fragment.sha256,'Actual embedded fragment and prefix');
equal(hash(vertex),gles.vertex.sha256,'Actual embedded vertex');
const buildPath=htmlPath.replace(/\.html$/,'.build.json');
const audit=JSON.parse(fs.readFileSync(buildPath,'utf8'));
equal(hash(html),audit.html_sha256,'HTML hash');
Object.assign(audit,{
 javascript_parse_passed:true,
 independent_source_embedding_check:true,
 exact_open_link_round_trip:true,
 native_gles_compiles_and_links:true,
 compiled_preamble_matches_actual_html:true,
 compiled_vertex_matches_actual_html:true,
 verification_scope:'Independent JavaScript parse and exact-source/preamble checks plus native GLES compilation/linking; no browser runtime test.'
});
fs.writeFileSync(buildPath,JSON.stringify(audit,null,2)+'\n');
process.stdout.write(JSON.stringify(audit,null,2)+'\n');
