// Run the production URL selection function; no renderer is mocked as proof.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(path.join(__dirname, '../cloud-v17/tools/build_player.py'), 'utf8');
const start = source.indexOf('function initialPreviewQuality(search,options){');
const end = source.indexOf('// Apply an explicit, visible cap', start);
assert.ok(start >= 0 && end > start);
const state = {URLSearchParams};
vm.runInNewContext(source.slice(start,end),state);
const options = ['auto','160','240','320','480','640','960'];
for (const value of options) {
  assert.equal(state.initialPreviewQuality('?preview='+value,options),value);
}
for (const query of ['', '?unrelated=160', '?preview=', '?preview=80', '?preview=160px',
  '?preview=1e3', '?preview=160&preview=320', '?preview=160&preview=160']) {
  assert.equal(state.initialPreviewQuality(query,options),'auto');
}
assert.equal(state.initialPreviewQuality('?unrelated=yes&preview=160',options),'160');
assert.equal(state.initialPreviewQuality('?preview=160',['auto','320']),'auto');
console.log('PASS: explicit initial preview uses only current UI options; absent/invalid/ambiguous values preserve Auto');
