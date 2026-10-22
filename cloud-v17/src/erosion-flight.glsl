#version 300 es
precision highp float;
precision highp int;
uniform vec2 iResolution;
uniform float iTime;
out vec4 fragColor;

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
