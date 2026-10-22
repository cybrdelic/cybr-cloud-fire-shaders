// pass1: 769x672, RGBA32F, NEAREST, recursion20. Uses its own previous output.
// The extra column persists the RK stage across interrupted recursion budgets.
void main(){
 ivec2 pixel=ivec2(gl_FragCoord.xy);
 ivec2 clockPixel=ivec2(2*TILE.x,0);
 float stage=texelFetch(u_pass1,clockPixel,0).x;
 if(pixel.x==clockPixel.x){fragColor=vec4(u_frame==0?0.:stage+1.,0,0,1);return;}
 int channel=pixel.x/TILE.x,bank=pixel.y/TILE.y;
 ivec3 p=voxel(pixel%TILE);
 if(u_frame==0){State s=initialState(p);fragColor=channel==0?s.a:s.b;return;}
 bool first=(int(stage)%2)==0;
 State old=readS(u_pass1,p,0),s=old;
 if(bank==1){
  if(first)s=sourceStep(old,DT*.5);
  else s=readS(u_pass1,p,1);
 }else{
  if(first)s=sourceStep(s,DT*.5);
  s=addS(s,mulS(flowRHS(u_pass1,p,primitive(s),first),DT));
  if(!first)s=sourceStep(mulS(addS(readS(u_pass1,p,1),s),.5),DT*.5);
 }
 fragColor=channel==0?s.a:s.b;
}
