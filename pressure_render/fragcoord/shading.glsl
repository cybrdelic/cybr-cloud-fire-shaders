// pass2: 384x336, RGBA16F, LINEAR, recursion1. Lighting only, no flow changes.
void main(){
 ivec3 cell=voxel(ivec2(gl_FragCoord.xy));
 State s=readS(u_pass1,cell,0),q=primitive(s);
 vec3 p=BMIN+(vec3(cell)+.5)*(BMAX-BMIN)/vec3(GRID);
 vec3 sun=normalize(vec3(-.5,.85,-.35));
 float tau=0.;
 for(int i=0;i<44;i++){
  vec3 at=p+sun*(float(i)+.5)*.5;
  if(any(lessThan(at,BMIN))||any(greaterThan(at,BMAX)))break;
  ivec3 j=ivec3((at-BMIN)/(BMAX-BMIN)*vec3(GRID));
  tau+=readS(u_pass1,j,0).b.w*SOOT_GAIN*.5;
 }
 vec3 emission=blackbody(300.*q.b.x/q.a.x);
 vec3 light=vec3(.006,.008,.011)+vec3(.080,.070,.055)*exp(-tau);
 fragColor=vec4(light+emission,max(s.b.w,0.)*SOOT_GAIN);
}
