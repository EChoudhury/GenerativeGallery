// Run: node tests/test_curator_feedback.cjs — no browser or provider requests.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('curator_platform/web/app.js','utf8');
const nodes=new Map();
const $=id=>{if(!nodes.has(id))nodes.set(id,{hidden:true,style:{},value:'chosen',textContent:'',scrollIntoView(){this.scrolled=true;}});return nodes.get(id);};
let accept,resolveCalled=false;
const ctx={$,Date,Math,JSON,console,crypto:{randomUUID:()=> 'task-id'},
 state:{providers:{stability:true,deepseek:true},artwork:{id:'artwork'},jobs:[],active:null,submitting:false},
 feedbackStarted:Date.now(),feedbackTimer:null,pollTimer:null,
 setInterval:()=>1,clearInterval:()=>{},setTimeout:()=>2,
 notify:()=>{},store:()=>{},recall:()=>null,
 api:()=>new Promise(resolve=>{accept=value=>{resolveCalled=true;resolve(value);};}),
 upsert:job=>ctx.state.jobs.push(job),completed:async()=>{},renderHistory:()=>{}};
vm.createContext(ctx);
const parts=[
 source.slice(source.indexOf('function refreshButtons()'),source.indexOf('function saveDraft()')),
 source.slice(source.indexOf('function showProgress(job)'),source.indexOf('function showRecording(job)'))
];
vm.runInContext(parts.join('\n'),ctx);
(async()=>{
 const request=ctx.startTask('grid',{method:'inpaint',bridge:20});
 assert.equal(resolveCalled,false);
 assert.equal($('task-progress').hidden,false,'feedback must show before submission finishes');
 assert.equal($('generate-grid').textContent,'Generating transition…');
 assert.equal($('generate-grid').disabled,true);
 assert.equal($('task-progress').scrolled,true);
 assert.match($('task-percent').textContent,/Elapsed \d+:\d{2}/);
 const job={id:'task-id',kind:'grid',status:'running',stage:'cell-1',message:'Generating A-side connection…',created_at:new Date(Date.now()-65000).toISOString(),payload:{method:'inpaint'}};
 accept(job);await request;
 ctx.showProgress(job);
 assert.equal($('task-stages').textContent,'Stage 2 / 4 · Generate A-side connection');
 assert.match($('task-percent').textContent,/Elapsed 1:05/);
 ctx.api=async()=>({...job,status:'completed'});
 await ctx.poll();
 assert.equal(ctx.state.active,null);
 assert.equal($('task-progress').hidden,true);
 assert.equal($('generate-grid').textContent,'Generate transition ↗');
 console.log('PASS: immediate feedback, busy button, actual stage, elapsed time and completion cleanup');
})().catch(error=>{console.error(error);process.exitCode=1;});
