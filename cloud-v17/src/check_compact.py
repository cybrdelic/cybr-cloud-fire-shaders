"""Verify reconstructed compact source and expanded offline shading agreement."""
from pathlib import Path
import os, sys, json, hashlib, time
os.environ.setdefault('LP_NUM_THREADS','8')
os.environ.setdefault('MESA_SHADER_CACHE_DIR','/tmp/cloud-render-mesa-cache')
sys.path.insert(0,'/tmp/cloud-render-deps')
import moderngl
import numpy as np

root=Path(__file__).resolve().parent
out=root.parent/'validation'/'compact'
out.mkdir(parents=True,exist_ok=True)
compact=(root/'erosion-flight.fragcoord.txt').read_bytes()
direct=(root/'erosion-flight.glsl').read_text().replace('#version 300 es','#version 330').replace('precision highp float;','').replace('precision highp int;','')
adapter=(root/'erosion-flight-adapter.glsl').read_text()
adapted='#version 330\nout vec4 fragColor;\n'+adapter+'''
void main() {
    vec3 ro,rd;
    camera(iTime,ro,rd,gl_FragCoord.xy);
    vec3 p=ro-rd/64.0;
    vec3 color=vec3(0);
    float transmittance=1.0;
    for(int i=0;i<2000&&transmittance>.005;++i) {
        p+=rd/32.0;
        float d=density(p);
        float attenuation=exp(-d/11.0);
        if(attenuation<1.0) {
            float sum=0.0;
            for(int j=0;j<64;++j)
                sum+=densityShadow(p+vec3(-2,3,1)*(float(j)+.5)/16.0);
            color+=transmittance*(1.0-attenuation)*shade(p,rd,d,sum*.68);
            transmittance*=attenuation;
        }
    }
    fragColor=vec4(displayTransform(color+transmittance*sky(rd)),1.0);
}
'''
vertex='#version 330\nin vec2 position;void main(){gl_Position=vec4(position,0,1);}'
ctx=moderngl.create_standalone_context(backend='egl',require=330)
vbo=ctx.buffer(np.array([-1,-1,3,-1,-1,3],dtype='f4').tobytes())
fbo=ctx.simple_framebuffer((32,18),components=4,dtype='f4');fbo.use()
programs=[]
for source in [direct,adapted]:
    p=ctx.program(vertex_shader=vertex,fragment_shader=source)
    p['iResolution'].value=(32,18)
    programs.append((p,ctx.vertex_array(p,[(vbo,'2f','position')])))
records=[]
for t in [0.,5.,239/24]:
    images=[]
    for p,vao in programs:
        p['iTime'].value=t
        vao.render()
        images.append(np.frombuffer(fbo.read(components=4,dtype='f4'),dtype='f4').copy())
    diff=np.abs(images[0]-images[1])
    record={'time':t,'all_finite':bool(all(np.isfinite(a).all() for a in images)),
            'max_abs_float_error':float(diff.max()),'mean_abs_float_error':float(diff.mean()),
            'quantized_changed_channels':int((np.rint(np.clip(images[0],0,1)*255)!=np.rint(np.clip(images[1],0,1)*255)).sum())}
    records.append(record)
    print(json.dumps(record),flush=True)
result={'character_count':len(compact),'under_500':len(compact)<500,'ascii':compact.isascii(),
        'compact_sha256':hashlib.sha256(compact).hexdigest(),
        'glsl_sha256':hashlib.sha256((root/'erosion-flight.glsl').read_bytes()).hexdigest(),
        'adapter_sha256':hashlib.sha256((root/'erosion-flight-adapter.glsl').read_bytes()).hexdigest(),
        'renderer':ctx.info['GL_RENDERER'],'dimensions':[32,18],
        'scope':'Native OpenGL GLSL compiler and direct-versus-adapter shading at three times. Not live FragCoord or WebGL validation.',
        'records':records,'passed':all(r['all_finite'] and r['max_abs_float_error']<2e-5 for r in records)}
(out/'compact-adapter-agreement.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'passed':result['passed'],'character_count':len(compact)}))
assert result['passed']
