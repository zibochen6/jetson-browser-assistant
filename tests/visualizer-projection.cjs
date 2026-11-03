const assert = require('node:assert/strict');
require('../src/jetson_browser/static/visualizer.js');
const {project, eventTime} = globalThis.JetsonFlow;
const events = [
  {actor:'qwen_parser',message:'Parse',elapsed_seconds:0,event_type:'operation',transition:'start',operation_id:'p',stage:'parse'},
  {actor:'qwen_parser',message:'Parse',elapsed_seconds:2,event_type:'operation',transition:'end',operation_id:'p',stage:'parse',duration_seconds:2},
  {actor:'site_adapter',message:'Calendar',elapsed_seconds:3,event_type:'operation',transition:'start',operation_id:'c',stage:'calendar'},
  {actor:'site_adapter',message:'Calendar click',elapsed_seconds:4,event_type:'operation',transition:'start',operation_id:'a',stage:'execute'},
  {actor:'site_adapter',message:'Calendar click',elapsed_seconds:5,event_type:'operation',transition:'end',operation_id:'a',stage:'execute',duration_seconds:1},
  {actor:'site_adapter',message:'Calendar',elapsed_seconds:6,event_type:'operation',transition:'end',operation_id:'c',stage:'calendar',duration_seconds:3},
  {actor:'service',message:'Cancelled',status:'CANCELLED',elapsed_seconds:7}
];
assert.equal(project(events,1).stage,'parse');
assert.equal(project(events,4.5).current.actor,'site_adapter');
assert.equal(project(events,4.5).stage,'execute');
assert.equal(project(events,5.5).stage,'calendar');
assert.equal(project(events,7).status,'CANCELLED');
assert.notEqual(project(events,7).stage,'done');
const result={status:'SUCCEEDED',finished_at:1010,total_seconds:10,query_completed:true};
assert.equal(project(events,.5,result).metrics.query_completed,undefined);
assert.equal(project(events,10,result).metrics.query_completed,true);
const old=[{actor:'laya',timestamp:'2026-11-03T00:00:02Z',message:'Choose'}];
const legacy=project(old,3,{submitted_at:Date.parse('2026-11-03T00:00:00Z')/1000});
assert.equal(legacy.stages.decide.seconds,null);
assert.equal(legacy.legacy,true);
const recovery=project([{actor:'qwen_recovery',elapsed_seconds:0,message:'Recover',selected_action:{id:'n2',label:'Nonstop'}}],1);
assert.equal(recovery.selectedBy,'Qwen recovery');
assert.equal(recovery.selected.label,'Nonstop');
assert.equal(eventTime(old[0],{submitted_at:Date.parse('2026-11-03T00:00:00Z')/1000},old),2);
console.log('Projection attribution, legacy timing and replay invariants passed');
