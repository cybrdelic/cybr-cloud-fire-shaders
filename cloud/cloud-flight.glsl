//[CONVERT] GLSL
float g(vec3 p,float b){float d = 1.2-length(vec3(mod(p.xz, 16.0)-8.0,p.y*.64))*.25; float a = .8;p*=.35;for(int _fc=0;float(_fc)<b&&d>-1.1*a;_fc++){float v = 1.0;for(int i=0;i<27;i++){vec3 q= vec3(floor(p)+vec3(ivec3(i,float(i)/3.0,float(i)/9.0)%3)-1.0);v=min(v,length(p-q-fract(sin(q+q.yzx+q.zxy*57.0)*1e4)));}d+=a*(.6-v);p=p*2.1+3.0;a*=.45;}return smoothstep(0.0, .16, d);}

void main() {
    vec3 r= vec3(normalize(vec3(gl_FragCoord.xy-u_resolution/2.0,u_resolution.y))); vec3 p=vec3(3.5,7.0-u_time/5.0,u_time)-r/64.0; vec3 c = vec3(0.0); vec3 k=vec3(.05,.18,.4)-r.y/9.0;float t = 1.0;for(int i=0;float(i)<2e3&&t>.005;i++){p+=r/32.0;float a = exp(-g(p,6.)/11.0); float s = 0.0;if(a<1.0){for(int j=0;j<64;j++)s+=g(p+vec3(-2.0, 3.0, -1.0)*(float(j)+.5)/48.0,4.);c+=t*(1.0-(a))*mix(k,vec3(4.0, 5.0, 6.0)/30.0+.78*exp(-s*.167),exp(-float(i)/1e3));t*=a;}}fragColor=vec4(sqrt(c+t*k), 1.0);
}