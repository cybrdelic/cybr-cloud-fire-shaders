from pathlib import Path
import json, hashlib, base64

ROOT = Path(__file__).resolve().parent
compact = 'f g(f3 p,f b){f d=.45-ab(p.y*.12),a=1.4;p*=.15;@(b&&d>-1.2*a){f v=1;@(i,27){f3 q=flr(p)+f3(i3(i,i/3,i/9)%3)-1;v=min(v,len(p-q-frc(sin(q+q.yzx+q.zxy*57)*1e4)));}d+=a*(.65-v);p=p*2.1+3;a*=.45;}return sms(0,.12,d);}f3 r=nor(f3(C.xy-R/2,R.y)),p=f3(3+sin(T*.2),8+T/4,T*1.6)-r/64,c,k=f3(.05,.18,.4)-r.y/9;f t=1;@(i,2e3&&t>.005){p+=r/32;f a=exp(-g(p,6.)/11),s;if(a<1){@(j,64)s+=g(p+f3(-2,3,1)*(f(j)+.5)/16,4.);c+=t*~a*mix(k,f3(4,5,6)/30+(.8-.4*r.x)*exp(-s*.68),exp(-i/1e3));t*=a;}}O=f4(sqt(c+t*k),1);'
assert len(compact) < 500 and compact.isascii()

core = '''
// Erosion Flight: reconstructed continuation, not recovered original V17 bytes.
// Continuous world-space Worley hierarchy replaces V16's periodic ellipsoid grid.
float g(vec3 p, float b) {
    float d = .45 - abs(p.y * .12);
    float a = 1.4;
    p *= .15;
    for (int octave = 0; float(octave) < b && d > -1.2*a; ++octave) {
        float v = 1.0;
        for (int i = 0; i < 27; ++i) {
            vec3 q = floor(p) + vec3(ivec3(i, i/3, i/9) % 3) - 1.0;
            v = min(v, length(p-q-fract(sin(q+q.yzx+q.zxy*57.0)*1e4)));
        }
        d += a*(.65-v);
        p = p*2.1+3.0;
        a *= .45;
    }
    return smoothstep(0.0, .12, d);
}
'''

main = '''
void mainImage(out vec4 color, in vec2 pixel) {
    vec3 r = normalize(vec3(pixel-iResolution/2.0, iResolution.y));
    vec3 p = vec3(3.0+sin(iTime*.2), 8.0+iTime/4.0, iTime*1.6)-r/64.0;
    vec3 c = vec3(0.0);
    vec3 k = vec3(.05,.18,.4)-r.y/9.0;
    float t = 1.0;
    for (int i = 0; i < 2000 && t > .005; ++i) {
        p += r/32.0;
        float a = exp(-g(p,6.0)/11.0);
        float s = 0.0;
        if (a < 1.0) {
            for (int j=0; j<64; ++j)
                s += g(p+vec3(-2,3,1)*(float(j)+.5)/16.0,4.0);
            c += t*(1.0-a)*mix(k,vec3(4,5,6)/30.0+(.8-.4*r.x)*exp(-s*.68),exp(-float(i)/1000.0));
            t *= a;
        }
    }
    color = vec4(sqrt(c+t*k),1.0);
}
void main() { mainImage(fragColor, gl_FragCoord.xy); }
'''

header = '''#version 300 es
precision highp float;
precision highp int;
uniform vec2 iResolution;
uniform float iTime;
out vec4 fragColor;
'''

adapter = 'uniform vec2 iResolution;\nuniform float iTime;\n' + core + '''
// Root cache integrator interface. sunTau is optical depth, not raw density sum.
const float EXTINCTION = 32.0/11.0;
const float SUN_EXTINCTION = .68*16.0/sqrt(14.0);
const float SUN_DISTANCE = 4.0*sqrt(14.0);
const vec3 SUN_DIR = vec3(-2.0,3.0,1.0)/sqrt(14.0);
const float VIEW_STEP = 1.0/32.0;
const float VIEW_DISTANCE = 62.5;
float density(vec3 p) { return g(p,6.0); }
float densityShadow(vec3 p) { return g(p,4.0); }
vec3 sky(vec3 rd) { return vec3(.05,.18,.4)-rd.y/9.0; }
vec3 origin(float t) { return vec3(3.0+sin(t*.2),8.0+t/4.0,t*1.6); }
void camera(float t, out vec3 ro, out vec3 rd, vec2 pixel) {
    ro=origin(t);
    rd=normalize(vec3(pixel-iResolution/2.0,iResolution.y));
}
vec3 shade(vec3 p, vec3 rd, float d, float sunTau) {
    float distanceAlongRay = max(0.0,length(p-origin(iTime))-.5*VIEW_STEP);
    vec3 ambient=vec3(4,5,6)/30.0;
    vec3 lit=ambient+(.8-.4*rd.x)*exp(-sunTau);
    return mix(sky(rd),lit,exp(-distanceAlongRay/31.25));
}
vec3 toneMap(vec3 linearColor) { return sqrt(max(linearColor,vec3(0))); }
vec3 displayTransform(vec3 linearColor) { return toneMap(linearColor); }
'''

(ROOT/'erosion-flight.fragcoord.txt').write_text(compact)
(ROOT/'erosion-flight.glsl').write_text(header+core+main)
(ROOT/'erosion-flight-adapter.glsl').write_text(adapter)
link='https://fragcoord.xyz/#code='+base64.urlsafe_b64encode(compact.encode()).decode().rstrip('=')
notes={
    'label':'Erosion Flight — reconstructed V17 continuation',
    'provenance':'Rebuilt from saved V16 source and V17 design records; original unfinished V17 source and frames were not saved.',
    'characters':len(compact), 'ascii':compact.isascii(), 'compact_sha256':hashlib.sha256(compact.encode()).hexdigest(),
    'density_octaves':6,'shadow_octaves':4,'density_static':True,
    'extinction':32/11,'sun_extinction':.68*16/(14**.5),
    'sun_direction':[-2/(14**.5),3/(14**.5),1/(14**.5)],'sun_probe_count':64,
    'sun_probe_distance':4*(14**.5),'sun_probe_step':(14**.5)/16,
    'view_step':1/32,'view_steps':2000,'view_distance':62.5,'early_termination':.005,
    'phase':'Compact linear directional response 0.8 - 0.4 * rd.x; not Henyey–Greenstein.',
    'camera':'(3+sin(t*0.2), 8+t/4, 1.6*t), fixed forward orientation, focal length 1.0 image heights.',
    'world_bounds_recommended':[-50,-18,-1,48,18,84],
    'limitations':['Static cloud density; movement is camera motion.','Ambient and aerial perspective are compact approximations.','No atmospheric transport or cloud-formation fluid solver.','Offline video should explicitly disclose cached density/light interpolation.'],
    'open_link':link,'open_link_round_trip':base64.urlsafe_b64decode(link.split('=')[1]+'='*((-len(link.split('=')[1]))%4)).decode()==compact,
    'glsl_conversion':'Manually expanded GLSL cross-checked against the official FragCoord GOLF converter bundle; converted output passed native GLES3 compile/link. No live browser playback validation.'
}
(ROOT/'erosion-flight.notes.json').write_text(json.dumps(notes,indent=2)+'\n')
print(json.dumps({'characters':len(compact),'source':str(ROOT/'erosion-flight.glsl'),'compact_sha256':notes['compact_sha256']}))
