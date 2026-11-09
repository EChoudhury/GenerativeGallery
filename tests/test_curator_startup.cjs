const fs=require('fs'),vm=require('vm');
const html=fs.readFileSync('curator_platform/web/index.html','utf8');
const source=fs.readFileSync('curator_platform/web/app.js','utf8');
const assert=require('node:assert/strict');
const artwork={id:'saved-art',title:'Saved work',artist:'Artist',notes:'',prompt:'Piano',created_at:'2026-10-22T10:00:00Z'};
const fixture={music:[{id:'music-a',name:'Saved music',artist:'Artist',artwork_title:'Saved work',is_loop:true,duration:16,audio_url:'/audio'}],job:[{id:'another-visitor-job',kind:'music',status:'running',payload:{},created_at:'2026-10-22T10:00:00Z'}],grid:[]};
class Element{
 constructor(){this.value='';this.hidden=false;this.style={setProperty(){}};this.dataset={};this.children=[];this.listeners={};this.classList={add(){},remove(){},toggle(){}};}
 addEventListener(type,fn){this.listeners[type]=fn;}append(...nodes){this.children.push(...nodes);}replaceChildren(...nodes){this.children=nodes;}setAttribute(){}removeAttribute(){}getAttribute(){return null;}pause(){}load(){}scrollIntoView(){}focus(){}reportValidity(){return true;}close(){}showModal(){}
 get firstElementChild(){return this.children[0]||(this.children[0]=new Element());}
}
const nodes=new Map([...html.matchAll(/id="([^"]+)"/g)].map(match=>[match[1],new Element()]));
async function check(configFails=false){
const calls=[];const persisted={'curator-grid':JSON.stringify('stale-grid-id')};
const ctx={console,Date,Math,JSON,crypto:{randomUUID:()=> 'new-artwork'},
 document:{getElementById:id=>nodes.get(id)||null,querySelectorAll:()=>[],createElement:()=>new Element(),addEventListener(){}},
 window:{addEventListener(){}},location:{hash:'#library'},localStorage:{getItem:key=>persisted[key]||null,setItem(key,value){persisted[key]=value;}},Option:class extends Element{constructor(label,value){super();this.text=label;this.value=value;}},setTimeout,clearTimeout,setInterval,clearInterval,
 fetch:async(path,options={})=>{calls.push(path);let result,ok=true;
 if(path==='/api/config'){if(configFails)throw new Error('Configuration temporarily unavailable');result={providers:{stability:true,deepseek:true}};}
 else if(path==='/api/music')result=fixture.music;
 else if(path==='/api/jobs')result=fixture.job;
 else if(path==='/api/grids')result=fixture.grid;
 else if(path==='/api/artworks')result=options.method==='POST'?artwork:[artwork];
 else if(path.startsWith('/api/grids/')){ok=false;result={detail:'Record not found.'};}
 return {ok,json:async()=>result};}

};vm.createContext(ctx);
vm.runInContext(source,ctx);
await new Promise(resolve=>setTimeout(resolve,20));
assert.equal(vm.runInContext('state.active',ctx),null,'another visitor task must not take over this browser');
assert.equal(vm.runInContext('state.library.length',ctx),1,'library must load even if config or stale grid fails');
assert.equal(nodes.get('music-library').children.length,1);
assert.equal(nodes.get('artwork-history').children.length,2,'saved artworks must be accessible');
assert.equal(JSON.parse(persisted['curator-grid']),null,'stale selection must not abort startup');
if(configFails){assert.match(nodes.get('interpret-status').textContent,/Add an artwork/);return;}
vm.runInContext('state.image="data:image/jpeg;base64,image"',ctx);
nodes.get('artwork-title').value='Saved work';nodes.get('artist').value='Artist';
vm.runInContext('refreshButtons()',ctx);
assert.equal(vm.runInContext('state.artwork',ctx),null);
assert.equal(nodes.get('generate-prompt').disabled,false,'complete unsaved fields must enable interpretation');
assert.match(nodes.get('interpret-status').textContent,/Artwork ready/);
ctx.submitted=[];
vm.runInContext('startTask=async(kind,values)=>{submitted.push({kind,values});}',ctx);
await nodes.get('generate-prompt').listeners.click();
assert.equal(ctx.submitted[0].kind,'prompt');
assert.equal(ctx.submitted[0].values.artwork_id,artwork.id,'artwork must be saved before task submission');
assert.equal(vm.runInContext('state.artworkDirty',ctx),false);
const count=calls.filter(path=>path==='/api/artworks').length;
await nodes.get('generate-prompt').listeners.click();
assert.equal(calls.filter(path=>path==='/api/artworks').length,count,'unchanged artwork must not create duplicate saved records');
nodes.get('artist').value=' ';vm.runInContext('refreshButtons()',ctx);
assert.equal(nodes.get('generate-prompt').disabled,true,'blank artist disables interpretation');
assert.equal(calls.filter(path=>path==='/api/jobs').length,1,'test must not invoke paid providers');
}
(async()=>{await check();await check(true);console.log('PASS: saved work discovery, stale-grid recovery, configuration failure isolation, and interpretation readiness and automatic save before generation');})().catch(error=>{console.error(error);process.exitCode=1;});
