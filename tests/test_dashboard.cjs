/* Offline registry fixtures; never reaches HA, a broker or a ventilation unit. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname,'../custom_components/ventaxia_econiq_readonly/frontend/dashboard.js'),'utf8');
const elements = new Map();
vm.runInNewContext(source, {HTMLElement:class {}, customElements:{get:k=>elements.get(k),define:(k,v)=>elements.set(k,v)}});
const strategy = elements.get('ll-strategy-dashboard-ventaxia-econiq');
const device = (id,unit,legacy=false) => ({id,name:'Synthetic ventilation',identifiers:[[legacy?'mqtt':'ventaxia_econiq_readonly',legacy?`ventaxia_readonly_${unit}`:unit]]});
const entity = (device,key,id,legacy=false) => ({device_id:device.id,entity_id:id,
  unique_id:`${legacy?'ventaxia_readonly_':''}${device.identifiers[0][1].replace(/^ventaxia_readonly_/,'')}_${key}`});
const calls=[];
function hass(devices,entities,states={}) {return {states,callWS:async req=>{calls.push(req.type);return req.type==='config/device_registry/list'?devices:entities;}};}
function references(config) {
  const result=[];
  function walk(x) {if (!x || typeof x!=='object') return; if (x.entity) result.push(x.entity); Object.values(x).forEach(v=>Array.isArray(v)?v.forEach(walk):walk(v));}
  walk(config);return result;
}
function assertSafe(config) {
  const serialized=JSON.stringify(config);
  for (const forbidden of ['call-service','perform-action','button','thermostat','command_topic','192.168.']) assert.ok(!serialized.includes(forbidden),forbidden);
  for (const ref of references(config)) assert.match(ref,/^(sensor|binary_sensor)\./);
}
(async()=>{
  const native=device('ha-a','SYNTH-A');
  const registry=[entity(native,'supply_temperature','sensor.renamed_temperature'),entity(native,'recovery_ratio','sensor.custom_ratio'),entity(native,'connection','binary_sensor.telemetry'),entity(native,'model_details','sensor.model')];
  let result=await strategy.generate({},hass([native],registry));
  assert.equal(result.views.length,4);assert.deepEqual(Array.from(result.views,v=>v.title),['Overview','Statistics','Diagnostics','Maintenance']);
  assert.ok(references(result).includes('sensor.renamed_temperature'));assertSafe(result);
  const percentileRegistry=['recovery_samples_24h','recovery_p10_24h','recovery_p90_24h'].map(key=>entity(native,key,`sensor.synthetic_${key}`));
  const pct=await strategy.generate({},hass([native],percentileRegistry));
  const conditional=pct.views[1].cards.find(c=>c.type==='conditional');
  assert.equal(conditional.conditions[0].above,19);
  assert.equal(conditional.conditions[0].entity,'sensor.synthetic_recovery_samples_24h');
  assertSafe(pct);
  const old=device('ha-old','SYNTH-OLD',true);
  result=await strategy.generate({},hass([old],[entity(old,'system_power','sensor.old_power',true)],{'sensor.mvhr_apparent_temperature_recovery':{state:'80'},'sensor.mvhr_energy_today':{state:'1'}}));
  assert.ok(references(result).includes('sensor.mvhr_apparent_temperature_recovery'));assert.ok(references(result).includes('sensor.mvhr_energy_today'));assertSafe(result);
  const second=device('ha-b','SYNTH-B');
  result=await strategy.generate({},hass([native,second],[...registry,entity(second,'supply_temperature','sensor.unit_b')]));
  assert.equal(result.views.length,8);assert.ok(result.views.slice(0,4).every(v=>!references(v).includes('sensor.unit_b')));assertSafe(result);
  result=await strategy.generate({device_id:'ha-b'},hass([native,second],[...registry,entity(second,'supply_temperature','sensor.unit_b')]));
  assert.equal(result.views.length,4);assert.ok(!references(result).includes('sensor.renamed_temperature'));
  result=await strategy.generate({device_id:'ha-old'},hass([old,native],[entity(old,'system_power','sensor.old_power',true)],{'sensor.mvhr_apparent_temperature_recovery':{state:'80'}}));
  assert.ok(!references(result).includes('sensor.mvhr_apparent_temperature_recovery'),'No shared legacy helpers when multiple units exist, even with explicit selection');
  result=await strategy.generate({},hass([native],[]));assert.equal(result.views.length,4);assert.equal(references(result).length,0);assertSafe(result);
  result=await strategy.generate({},hass([],[]));assert.equal(result.views.length,1);assert.match(JSON.stringify(result),/No compatible/);
  result=await strategy.generate({device_id:'missing'},hass([native],registry));assert.match(JSON.stringify(result),/selected Home Assistant device UUID/);
  result=await strategy.generate({}, {callWS:async()=>{throw Error('blocked');}});assert.match(JSON.stringify(result),/Unable to read/);
  const disabled={...registry[0],disabled_by:'user'};const unsafe={...registry[0],entity_id:'switch.unsafe'};
  result=await strategy.generate({},hass([native],[disabled,unsafe]));assert.equal(references(result).length,0);
  assert.ok(calls.every(c=>['config/entity_registry/list','config/device_registry/list'].includes(c)));
  console.log('Dashboard offline tests passed: native, legacy, renamed, multi-unit, missing, selection, failure and read-only guards.');
})().catch(error=>{console.error(error);process.exitCode=1;});
