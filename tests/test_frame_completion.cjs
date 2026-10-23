// Exercise production completion ordering; fake fences are not rendering proof.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(path.join(__dirname, '../cloud-v17/tools/build_player.py'), 'utf8');
const start = source.indexOf('function completePending(now){');
const end = source.indexOf('function tick(now){', start);
assert.ok(start >= 0 && end > start);
function fixture(status) {
  const result = {pending:{sync:7,started:0,scene:'erosion',generation:3,frame:1,time:0,width:160,height:90},
    sceneKey:'erosion',sceneGeneration:3,displayedTime:0,emaFrameMs:0,completedFrames:0,lastCompleted:null,
    qualityPicker:{value:'160'},autoCap:320,dirty:false,failed:false,deleted:[],errors:[]};
  result.gl={ALREADY_SIGNALED:1,CONDITION_SATISFIED:2,WAIT_FAILED:3,
    clientWaitSync:()=>status,deleteSync:value=>result.deleted.push(value)};
  result.error=(...details)=>{result.failed=true;result.errors.push(details);};
  vm.runInNewContext(source.slice(start,end),result);
  return result;
}
for (const status of [1,2]) {
  const state=fixture(status);
  assert.equal(state.completePending(11000),true);
  assert.equal(state.completedFrames,1);
  assert.equal(state.lastCompleted.scene,'erosion');
  assert.equal(state.emaFrameMs,11000);
  assert.equal(state.failed,false);
}
const stalled=fixture(4);
assert.equal(stalled.completePending(9999),false);
assert.equal(stalled.failed,false);
assert.equal(stalled.completePending(11000),false);
assert.equal(stalled.failed,true);
assert.equal(stalled.completedFrames,0);
assert.equal(stalled.pending,null);
const stale=fixture(1);stale.sceneGeneration=4;
assert.equal(stale.completePending(11000),true);
assert.equal(stale.completedFrames,0);
assert.equal(stale.lastCompleted,null);
const failed=fixture(3);
assert.equal(failed.completePending(1),false);
assert.equal(failed.failed,true);
assert.equal(failed.completedFrames,0);
console.log('PASS: completed fences precede elapsed checks; pending deadlines and generation checks retained');
