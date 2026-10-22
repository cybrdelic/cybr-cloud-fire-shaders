uniform vec2 iResolution;
uniform float iTime;

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
