// CLOUD FLIGHT / V17 RECONSTRUCTION
// Procedural single-fragment cloudscape. No image textures or generated images.
// Rebuilt from the recorded V17 design after its unsaved working files were lost.
// This file is an ES 3 / desktop-GL-compatible shader body: the host supplies
// #version and an output variable, then calls mainImage from main().
uniform vec2 iResolution;
uniform float iTime;

const vec3 SUN_DIR = vec3(-0.5271685, 0.6853190, 0.5024253);
const float EXTINCTION = 1.65;
const vec3 VOLUME_MIN = vec3(-44.0, -12.0, -20.0);
const vec3 VOLUME_MAX = vec3(48.0, 35.0, 112.0);

float hash13(vec3 p) {
    p = fract(p * 0.1031);
    p += dot(p, p.zyx + 33.33);
    return fract((p.x + p.y) * p.z);
}

float noise3(vec3 p) {
    vec3 i = floor(p), f = fract(p);
    f = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);
    vec4 a = vec4(hash13(i), hash13(i + vec3(1,0,0)),
                  hash13(i + vec3(0,1,0)), hash13(i + vec3(1,1,0)));
    vec4 b = vec4(hash13(i + vec3(0,0,1)), hash13(i + vec3(1,0,1)),
                  hash13(i + vec3(0,1,1)), hash13(i + vec3(1,1,1)));
    vec4 c = mix(a,b,f.z);
    return mix(mix(c.x,c.y,f.x), mix(c.z,c.w,f.x), f.y);
}

float envelope(vec3 p, vec3 center, vec3 radius) {
    return 1.0 - length((p-center)/radius);
}

float formation(vec3 p) {
    // Unequal overlapping formations replace the old periodic ellipsoid grid.
    // Their bases are curved and individually placed; there is no ground plane.
    float d = envelope(p,vec3(-13.0,3.2,6.0),vec3(11.0,8.0,12.0));
    d=max(d,envelope(p,vec3(-10.8,9.0,13.5),vec3(6.5,8.0,7.5)));
    d=max(d,envelope(p,vec3(-19.0,7.0,19.0),vec3(8.0,10.0,9.0)));
    d=max(d,envelope(p,vec3(12.3,3.0,17.0),vec3(12.0,7.0,13.0)));
    d=max(d,envelope(p,vec3(11.6,9.0,19.0),vec3(7.3,8.6,7.5)));
    d=max(d,envelope(p,vec3(18.5,12.0,27.0),vec3(7.8,9.0,7.0)));
    d=max(d,envelope(p,vec3(-14.0,6.0,40.0),vec3(12.0,11.0,14.0)));
    d=max(d,envelope(p,vec3(-10.7,15.0,42.0),vec3(6.8,9.0,7.7)));
    d=max(d,envelope(p,vec3(-24.0,9.0,48.0),vec3(10.0,9.5,11.0)));
    d=max(d,envelope(p,vec3(16.0,5.0,52.0),vec3(15.0,8.5,13.5)));
    d=max(d,envelope(p,vec3(21.0,15.5,56.0),vec3(7.3,10.5,9.0)));
    d=max(d,envelope(p,vec3(6.0,10.7,64.0),vec3(7.5,8.0,9.0)));
    d=max(d,envelope(p,vec3(-6.0,4.0,75.0),vec3(15.0,9.0,14.0)));
    d=max(d,envelope(p,vec3(-9.0,13.5,80.0),vec3(8.0,11.0,9.0)));
    d=max(d,envelope(p,vec3(27.0,6.0,89.0),vec3(14.0,10.0,14.0)));
    d=max(d,envelope(p,vec3(-26.0,4.0,95.0),vec3(12.0,9.0,13.0)));
    // Lower, detached companions give the reveal a second height scale.
    d=max(d,envelope(p,vec3(1.0,0.0,37.0),vec3(6.0,4.3,8.0)));
    d=max(d,envelope(p,vec3(-1.0,1.0,57.0),vec3(7.0,4.0,7.0)));
    return d;
}

float density(vec3 p) {
    float e=formation(p);
    if(e < -0.30) return 0.0;
    // Broad convection-like distortions stay coherent across the surface.
    vec3 warp=vec3(noise3(p*.105+vec3(8.1,2.2,6.7)),
                   noise3(p*.093+vec3(3.3,12.1,1.0)),
                   noise3(p*.111+vec3(17.2,4.1,9.4)))-.5;
    vec3 q=p+warp*2.4;
    float broad=noise3(q*.29+vec3(5.4,6.9,2.0));
    float billow=noise3(q*.67+vec3(11.1,4.5,3.9));
    // High-frequency erosion affects the boundary most strongly. Dense cores
    // remain optically thick instead of becoming a uniformly porous foam.
    float edge=1.0-smoothstep(.30,.65,e);
    float fine=noise3(q*1.55+vec3(2.2,7.7,1.9));
    float micro=noise3(q*3.45+vec3(8.1,5.8,12.3));
    float field=e-.20 + .47*(broad-.46) + .23*(billow-.44)
              + edge*(.105*(fine-.44)+.043*(micro-.42));
    // Finite continuous transition; no hard clipping against a height plane.
    return smoothstep(-.012,.055,field)*(.64+.36*smoothstep(.12,.58,e));
}

float densityShadow(vec3 p) { return density(p); }

vec3 sky(vec3 rd) {
    float h=clamp(rd.y*.75+.24,0.0,1.0);
    vec3 c=mix(vec3(.12,.24,.40),vec3(.016,.072,.19),pow(h,.55));
    float mu=max(dot(rd,SUN_DIR),0.0);
    c+=vec3(.20,.17,.12)*pow(mu,18.0);
    c+=vec3(1.5,1.27,.93)*pow(mu,680.0);
    return c;
}

float hg(float mu,float g) {
    return (1.0-g*g)/pow(max(.045,1.0+g*g-2.0*g*mu),1.5);
}

vec3 shade(vec3 p,vec3 rd,float d,float sunTau) {
    float mu=dot(rd,SUN_DIR);
    float phase=.26+.50*hg(mu,.56)+.07*hg(mu,-.28);
    float direct=exp(-sunTau);
    // Two broader, weaker scattering lobes provide thick-cloud illumination.
    // This is an appearance approximation, not a multiple-scattering solver.
    float multi=.25*exp(-sunTau*.28)+.07*exp(-sunTau*.075);
    float heightFill=mix(.07,.17,smoothstep(-4.0,22.0,p.y));
    vec3 ambient=vec3(.42,.56,.76)*heightFill;
    vec3 solar=vec3(1.16,1.10,.98)*(1.35*phase*direct+multi);
    return ambient+solar;
}

void camera(float time,out vec3 ro,out vec3 rd,vec2 fragCoord) {
    float t=clamp(time/10.0,0.0,1.0);
    float reveal=smoothstep(.48,1.0,t);
    ro=vec3(.7+2.0*sin(t*3.5),8.2-.8*sin(t*3.14159265)+18.0*reveal,-9.0+36.0*t);
    ro.x+=3.0*(smoothstep(.28,.63,t)-smoothstep(.56,.77,t));
    vec3 target=ro+vec3(-.75+1.7*sin(t*2.3),1.1-6.3*reveal,17.0);
    vec3 forward=normalize(target-ro);
    vec3 right=normalize(cross(vec3(0,1,0),forward));
    vec3 up=cross(forward,right);
    vec2 uv=(2.0*fragCoord-iResolution)/iResolution.y;
    rd=normalize(forward*1.78+right*uv.x+up*uv.y);
}

float sunlight(vec3 p) {
    float tau=0.0;
    const float stepSize=.48;
    for(int k=0;k<96;k++) {
        tau+=density(p+SUN_DIR*((float(k)+.5)*stepSize))*stepSize*EXTINCTION;
        if(tau>16.0)break;
    }
    return tau;
}

vec2 volumeHit(vec3 ro,vec3 rd) {
    vec3 inv=1.0/rd;
    vec3 a=(VOLUME_MIN-ro)*inv,b=(VOLUME_MAX-ro)*inv;
    vec3 mn=min(a,b),mx=max(a,b);
    return vec2(max(max(mn.x,mn.y),mn.z),min(min(mx.x,mx.y),mx.z));
}

vec3 displayTransform(vec3 linearColor) {
    // Fixed exposure and smooth shoulder; the RGB components stay coupled.
    vec3 c=linearColor*1.0;
    c=(c*(2.51*c+.03))/(c*(2.43*c+.59)+.14);
    return pow(clamp(c,0.0,1.0),vec3(1.0/2.2));
}

void mainImage(out vec4 fragColor,in vec2 fragCoord) {
    vec3 ro,rd;camera(iTime,ro,rd,fragCoord);
    vec3 background=sky(rd),radiance=vec3(0.0);
    float transmittance=1.0;
    vec2 hit=volumeHit(ro,rd);
    float travel=max(0.0,hit.x);
    const float stepSize=.065;
    for(int k=0;k<2400;k++) {
        if(travel>hit.y||transmittance<.002)break;
        vec3 p=ro+rd*(travel+stepSize*.5);
        float d=density(p);
        if(d>.00001) {
            float opacity=1.0-exp(-d*EXTINCTION*stepSize);
            vec3 lit=shade(p,rd,d,sunlight(p));
            float aerial=exp(-travel*.009);
            lit=mix(background,lit,aerial);
            radiance+=transmittance*opacity*lit;
            transmittance*=1.0-opacity;
        }
        travel+=stepSize;
    }
    fragColor=vec4(displayTransform(radiance+transmittance*background),1.0);
}
