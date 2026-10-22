// Main pass. Trilinear interpolation within the shaded 3D atlas.
vec4 field(vec3 world){
 vec3 p=clamp((world-BMIN)/(BMAX-BMIN)*vec3(GRID)-.5,vec3(0),vec3(GRID-1));
 int z=int(floor(p.z)),zz=min(z+1,GRID.z-1);
 vec2 a=vec2((z%8)*GRID.x,(z/8)*GRID.y)+p.xy+.5;
 vec2 b=vec2((zz%8)*GRID.x,(zz/8)*GRID.y)+p.xy+.5;
 return mix(texture(u_pass2,a/vec2(TILE)),texture(u_pass2,b/vec2(TILE)),fract(p.z));
}
vec3 film(vec3 x){return clamp((x*(2.51*x+.03))/(x*(2.43*x+.59)+.14),0.,1.);}
void main(){
 vec3 eye=vec3(5,4.2,-10.5),target=vec3(0,2.6,0);
 vec3 w=normalize(target-eye),u=normalize(cross(w,vec3(0,1,0))),v=cross(u,w);
 vec2 q=(gl_FragCoord.xy-.5*u_resolution)/u_resolution.y;
 vec3 rd=normalize(w*1.75+u*q.x+v*q.y);
 vec3 ia=(BMIN-eye)/rd,ib=(BMAX-eye)/rd;
 vec3 n=min(ia,ib),f=max(ia,ib);
 float a=max(max(n.x,n.y),n.z),b=min(min(f.x,f.y),f.z),trans=1.;
 vec3 sky=mix(vec3(.24,.29,.34),vec3(.12,.19,.27),smoothstep(-.2,.5,rd.y));
 sky+=vec3(.18,.16,.12)*pow(max(dot(rd,normalize(vec3(-.5,.85,-.35))),0.),12.);
 vec3 sum=vec3(0);
 if(b>max(a,0.)){
  a=max(a,0.);int count=int(ceil((b-a)/.075));float ds=(b-a)/float(count);
  for(int i=0;i<400;i++){
   if(i>=count||trans<.001)break;
   vec4 s=field(eye+rd*(a+(float(i)+.5)*ds));
   float alpha=1.-exp(-s.a*ds);sum+=trans*alpha*s.rgb;trans*=1.-alpha;
  }
 }
 fragColor=vec4(pow(film((sum+trans*sky)*.8),vec3(1./2.2)),1);
}
