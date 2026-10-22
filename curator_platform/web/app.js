'use strict';
const $ = id => document.getElementById(id);
const store = (key, value) => {try { localStorage.setItem('curator-'+key, JSON.stringify(value)); } catch { /* The app also works without browser storage. */ }};
const recall = (key, fallback=null) => {try { return JSON.parse(localStorage.getItem('curator-'+key)) ?? fallback; } catch {return fallback;}};
const state = {providers:{}, artwork:null, image:null, library:[], jobs:[], grids:[], selected:recall('selection',[]), active:null, recording:null, loop:null, bridge:null, grid:null, rename:null, submitting:false, artworkDirty:false, view:'create'};
let pollTimer;
let audioContext, gridNodes=[], gridPlaying=false, gridLoading=false;
const text = (tag, content, className='') => {const node=document.createElement(tag);node.textContent=content;if(className)node.className=className;return node;};
function notify(message, success=false) { $('notice').textContent=message;$('notice').className='notice'+(success?' success':'');$('notice').hidden=!message; }
async function api(path, body, method='POST') {
 const response=await fetch(path, {cache:'no-store', ...(body!==undefined?{method,headers:{'Content-Type':'application/json','X-Curator-Request':'1'},body:JSON.stringify(body)}:{})});
 let result;try {result=await response.json();} catch {throw new Error('The local service could not be reached. Keep its terminal open, then refresh.');}
 if(!response.ok)throw new Error(typeof result.detail==='string'?result.detail:'Please check the values and try again.');
 return result;
}
function go(view) {if(!['create','library','transition','grid'].includes(view))view='create';location.hash=view;showView(view);}
function showView(view) {
 state.view=view;
 for(const name of ['create','library','transition','grid'])$('view-'+name).hidden=name!==view;
 document.querySelectorAll('[data-view]').forEach(link=>link.classList.toggle('active',link.dataset.view===view));
 $('breadcrumb').textContent=({create:'CREATE A SOUND',library:'MUSIC LIBRARY',transition:'BETWEEN ARTWORKS',grid:'LISTENING GRID'})[view];
 if(view!=='grid'&&gridPlaying)stopGrid();
}
window.addEventListener('hashchange',()=>{const [view,id]=location.hash.slice(1).split('/');if(['create','library','transition','grid'].includes(view))showView(view);if(view==='grid'&&id)chooseGrid(id).catch(error=>notify(error.message));});
document.querySelectorAll('.workflow a').forEach(link=>link.addEventListener('click',event=>{event.preventDefault();document.querySelector(link.getAttribute('href')).scrollIntoView({behavior:'smooth',block:'start'});}));
function refreshButtons() {
 const busy=!!state.active||state.submitting;
 $('save-artwork').disabled=busy;
 $('generate-prompt').disabled=busy||!state.artwork||state.artworkDirty||!state.providers.deepseek;
 $('generate-music').disabled=busy||!state.artwork||state.artworkDirty||!state.providers.stability||!$('music-prompt').value.trim();
 $('process-loop').disabled=busy||!state.recording;
 $('save-music').disabled=busy||!state.loop;
 const endpoints=$('endpoint-a').value&&$('endpoint-b').value&&$('endpoint-a').value!==$('endpoint-b').value;
 for(const name of ['preview-bridge','generate-grid'])$(name).disabled=busy||!endpoints||!state.providers.stability;
 $('build-from-bridge').disabled=busy||!state.bridge||!state.providers.stability;
 $('prompt-count').textContent=$('music-prompt').value.length+' / 9000';
}
function saveDraft() {store('draft',{artworkId:state.artwork?.id,title:$('artwork-title').value,artist:$('artist').value,notes:$('curator-notes').value,prompt:$('music-prompt').value,duration:$('duration').value});}
for(const id of ['artwork-title','artist','curator-notes','music-prompt','duration'])$(id).addEventListener('input',()=>{if(['artwork-title','artist','curator-notes'].includes(id)){state.artworkDirty=true;$('artwork-status').textContent='Click “Use this artwork” to save your changes before generating.';}saveDraft();refreshButtons();});
async function loadConfig() {
 const result=await api('/api/config');state.providers=result.providers;
 $('connection-status').textContent=result.providers.stability&&result.providers.deepseek?'Providers configured':'Provider setup';
 $('connection-status').classList.toggle('ready',result.providers.stability&&result.providers.deepseek);
 $('setup-banner').hidden=result.providers.deepseek&&result.providers.stability;
 if(!result.providers.stability)$('setup-banner').firstElementChild.textContent='Add your Stability key to generate music. Add a DeepSeek key for artwork-to-prompt interpretation.';
 else $('setup-banner').firstElementChild.textContent='Connect DeepSeek to turn your artwork image into a music prompt. You can also write a prompt yourself.';
 $('settings-provider-status').replaceChildren();
 for(const [provider,ready] of Object.entries(result.providers)){const row=text('div','','provider-row');row.append(text('span',provider==='stability'?'Stability AI · music':'DeepSeek · image interpretation'),text('strong',ready?'Key configured':'Key needed'));$('settings-provider-status').append(row);}
 refreshButtons();
}
for(const id of ['open-settings','connection-status','setup-action'])$(id).addEventListener('click',()=>$('settings-dialog').showModal());
$('check-connections').addEventListener('click',async()=>{try{await loadConfig();notify('Configuration refreshed. No provider requests were made.',true);}catch(error){notify(error.message);}});

async function acceptImage(file) {
 if(!file)return;
 if(!['image/jpeg','image/png','image/webp'].includes(file.type)||file.size>8_000_000){notify('Choose a JPG, PNG or WebP image under 8 MB.');return;}
 try{
 const original=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(new Error('Could not read the image.'));reader.readAsDataURL(file);});
 const image=new Image();image.src=original;await image.decode();
 if(image.width*image.height>24_000_000)throw new Error('Please use an image smaller than 24 megapixels.');
 const scale=Math.min(1,1600/Math.max(image.width,image.height));const canvas=document.createElement('canvas');canvas.width=Math.round(image.width*scale);canvas.height=Math.round(image.height*scale);canvas.getContext('2d').drawImage(image,0,0,canvas.width,canvas.height);
 state.artworkDirty=true;refreshButtons();state.image=canvas.toDataURL('image/jpeg',.9);$('image-preview').src=state.image;$('image-preview').hidden=false;$('upload-placeholder').hidden=true;$('replace-image').hidden=false;
 $('artwork-status').textContent='Image ready. Click “Use this artwork” to save the updated artwork.';notify('');
 }catch(error){notify(error.message||'This image could not be opened.');}
}
$('artwork-file').addEventListener('change',event=>acceptImage(event.target.files[0]));
for(const type of ['dragenter','dragover'])$('upload-area').addEventListener(type,event=>{event.preventDefault();$('upload-area').classList.add('dragover');});
for(const type of ['dragleave','drop'])$('upload-area').addEventListener(type,event=>{event.preventDefault();$('upload-area').classList.remove('dragover');if(type==='drop')acceptImage(event.dataTransfer.files[0]);});
$('artwork-form').addEventListener('submit',async event=>{
 event.preventDefault();if(state.submitting||state.active)return;
 if(!state.image){notify('Upload an artwork image first.');$('artwork-file').focus();return;}
 state.submitting=true;refreshButtons();
 try{state.artwork=await api('/api/artworks',{title:$('artwork-title').value.trim(),artist:$('artist').value.trim(),notes:$('curator-notes').value,image:state.image});state.artworkDirty=false;saveDraft();$('artwork-status').textContent='Saved: '+state.artwork.title+' · '+state.artwork.artist;$('prompt-section').scrollIntoView({behavior:'smooth'});notify('Artwork saved. Interpret the image with DeepSeek, or write a music prompt yourself.',true);}
 catch(error){notify(error.message);}finally{state.submitting=false;refreshButtons();}
});
function renderAnalysis(result) {
 $('analysis').hidden=false;$('analysis-content').replaceChildren();
 $('analysis-content').append(text('p','Visual reading: '+result.visual_reading),text('p','Context & meaning: '+result.context_reading));const list=document.createElement('ul');for(const item of result.mapping)list.append(text('li',item));$('analysis-content').append(list);
}
function upsert(job) {state.jobs=[job,...state.jobs.filter(x=>x.id!==job.id)].sort((a,b)=>b.created_at.localeCompare(a.created_at));}
function renderHistory() {
 const select=$('generation-history'), selected=state.recording?.id;select.replaceChildren(new Option('Open a previous generation',''));
 for(const job of state.jobs.filter(x=>x.kind==='music'&&x.status==='completed'))select.append(new Option((job.payload.name||'Artwork recording')+' · '+new Date(job.created_at).toLocaleString(),job.id));
 select.value=selected||'';
}
function showProgress(job) {
 $('task-progress').hidden=false;$('task-label').textContent=job.message||'Working…';
 $('task-detail').textContent=job.kind==='grid'?(job.payload.method==='inpaint'?'Inpaint A/B → extract middle → inpaint A/middle and middle/B → saved grid.':'Bridge → middle excerpt → two variations → saved grid.')+' Generation stages, not an estimated finish time.':job.kind==='loop'?'Local processing. No API credits.':'Your task is saved. You can change pages or refresh without submitting again.';
 $('progress-fill').style.width=(job.progress||5)+'%';$('task-percent').textContent='';
}
async function startTask(kind, values={}) {
 if(state.active||state.submitting)return;
 state.submitting=true;refreshButtons();notify('');
 const payload={kind,...values};const saved=recall('pending');
 const requestId=saved&&JSON.stringify(saved.payload)===JSON.stringify(payload)?saved.id:crypto.randomUUID();
 store('pending',{id:requestId,payload});
 try{
  const job=await api('/api/jobs',{...payload,request_id:requestId});store('pending',null);store('last-task',job.id);upsert(job);
  if(job.status==='completed'){await completed(job);}else if(job.status==='failed'){notify(job.error);}else{state.active=job.id;showProgress(job);pollTimer=setTimeout(poll,1000);}
 }catch(error){
  notify(error.message);
  try{const history=await api('/api/jobs');state.jobs=history;const active=history.find(x=>!['completed','failed'].includes(x.status));if(active){state.active=active.id;showProgress(active);pollTimer=setTimeout(poll,1500);}}catch{/* Preserve the pending id for an idempotent manual retry. */}
 }finally{state.submitting=false;refreshButtons();}
}
async function poll() {
 if(!state.active)return;
 try{const job=await api('/api/jobs/'+state.active);upsert(job);showProgress(job);
  if(['completed','failed'].includes(job.status)){
   state.active=null;$('task-progress').hidden=true;
   if(job.status==='completed')await completed(job);else notify(job.error+' Partial files have been retained.');
  }
 }catch(error){$('task-detail').textContent='Reconnecting to the local service. Do not submit another generation.';}
 refreshButtons();if(state.active)pollTimer=setTimeout(poll,2500);
}
function showRecording(job) {
 state.recording=job;state.loop=null;store('recording',job.id);store('loop',null);
 $('music-empty').hidden=true;$('music-result').hidden=false;$('loop-result').hidden=true;
 $('recording-title').textContent=job.payload.name||'Artwork recording';$('recording-meta').textContent=job.result.duration.toFixed(2)+' seconds · WAV · stereo';
 $('original-audio').pause();$('original-audio').src='/api/jobs/'+job.id+'/audio';$('original-download').href='/api/jobs/'+job.id+'/audio?download=true';
 $('loop-start').value=0;$('loop-end').value=job.result.duration;$('loop-overlap').value=Math.min(1,Math.max(.05,Math.floor(job.result.duration/4*20)/20));
 $('loop-audio').pause();$('loop-audio').removeAttribute('src');$('music-name').value=job.payload.name||'Artwork loop';$('save-status').textContent='';updateLoopNote();renderHistory();refreshButtons();
}
function showLoop(job) {
 state.loop=job;store('loop',job.id);$('loop-result').hidden=false;
 $('loop-audio').src='/api/jobs/'+job.id+'/audio';$('loop-meta').textContent=job.result.duration.toFixed(2)+' seconds · '+job.result.overlap.toFixed(2)+' s overlap · WAV';
 $('music-name').value=state.recording?.payload.name||'Artwork loop';$('save-status').textContent='';refreshButtons();
}
function showBridge(job) {
 state.bridge=job;store('bridge',job.id);$('bridge-preview').hidden=false;
 $('bridge-audio').src='/api/jobs/'+job.id+'/audio';$('middle-start').value=job.result.start;$('middle-end').value=job.result.end;
 $('middle-start').min=job.result.start;$('middle-start').max=job.result.end;$('middle-end').min=job.result.start;$('middle-end').max=job.result.end;
 $('bridge-preview-description').textContent=`Full audition: ${job.result.duration.toFixed(1)} seconds. The generated interval is ${job.result.start.toFixed(1)}–${job.result.end.toFixed(1)} s. The two reference ends are excluded from the default middle selection.`;
 $('endpoint-a').value=job.result.a_id;$('endpoint-b').value=job.result.b_id;syncEndpoints(false);refreshButtons();
}
async function completed(job) {
 store('last-applied-task',job.id);renderHistory();
 if(job.kind==='prompt'){$('music-prompt').value=job.result.music_prompt;renderAnalysis(job.result);saveDraft();go('create');notify('Interpretation ready. Edit the music prompt before generating.',true);$('prompt-section').scrollIntoView({behavior:'smooth'});}
 if(job.kind==='music'){showRecording(job);go('create');$('music-section').scrollIntoView({behavior:'smooth'});notify('Recording ready. Listen, choose an excerpt, and prepare your loop.',true);}
 if(job.kind==='loop'){showLoop(job);go('create');$('loop-section').scrollIntoView({behavior:'smooth'});notify('Loop ready. Give it a name and save it to the library.',true);}
 if(job.kind==='bridge'){showBridge(job);go('transition');$('bridge-preview').scrollIntoView({behavior:'smooth'});notify('Bridge ready. The default selection keeps only the generated middle.',true);}
 if(job.kind==='grid'){await loadGrids();await chooseGrid(job.result.grid_id);go('grid');notify('Your five-cell gallery is ready. Start listening and move between the artworks.',true);}
 refreshButtons();
}
$('generate-prompt').addEventListener('click',()=>{if(!$('duration').reportValidity())return;startTask('prompt',{artwork_id:state.artwork.id,duration:Number($('duration').value)});});
$('generate-music').addEventListener('click',()=>{if(!$('duration').reportValidity())return;startTask('music',{artwork_id:state.artwork.id,duration:Number($('duration').value),prompt:$('music-prompt').value.trim(),name:state.artwork.title});});
$('generation-history').addEventListener('change',event=>{const job=state.jobs.find(x=>x.id===event.target.value);if(job)showRecording(job);});
function updateLoopNote() {const length=Number($('loop-end').value)-Number($('loop-start').value),overlap=Number($('loop-overlap').value);$('loop-duration-note').textContent=length>0&&length>2*overlap?`${length.toFixed(2)} s excerpt → ${(length-overlap).toFixed(2)} s loop. The original stays unchanged. Timing and harmony still need listening.`:'Choose a valid excerpt and an overlap shorter than half its duration.';}
for(const id of ['loop-start','loop-end','loop-overlap'])$(id).addEventListener('input',()=>{updateLoopNote();if(state.loop){state.loop=null;$('loop-result').hidden=true;store('loop',null);refreshButtons();}});
$('process-loop').addEventListener('click',()=>{for(const id of ['loop-start','loop-end','loop-overlap'])if(!$(id).reportValidity())return;startTask('loop',{source_job_id:state.recording.id,start:Number($('loop-start').value),end:Number($('loop-end').value),overlap:Number($('loop-overlap').value)});});
$('save-music').addEventListener('click',async()=>{
 if(!state.loop||!$('music-name').reportValidity())return;const name=$('music-name').value.trim();if(!name){$('music-name').focus();return;}
 const key=state.loop.id+'|'+name;let previous=recall('save-request');if(!previous||previous.key!==key){previous={key,id:crypto.randomUUID()};store('save-request',previous);}
 $('save-music').disabled=true;
 try{await api('/api/music',{source_job_id:state.loop.id,name,request_id:previous.id});await loadLibrary();$('save-status').textContent='Saved as “'+name+'”. It is now available in your library and transition selectors.';notify('Saved to your music library.',true);go('library');}
 catch(error){notify(error.message);}finally{refreshButtons();}
});

function renderLibrary() {
 const query=$('library-search').value.trim().toLowerCase();const visible=state.library.filter(item=>[item.name,item.artist,item.artwork_title].join(' ').toLowerCase().includes(query));
 $('music-library').replaceChildren();$('library-count').textContent=state.library.length;$('library-summary').textContent=visible.length+' saved '+(visible.length===1?'recording':'recordings');$('library-empty').hidden=state.library.length>0;
 if(!visible.length&&state.library.length)$('music-library').append(text('p','No recordings match your search.','field-note'));
 for(const item of visible){
  const card=text('article','','music-card');const selection=state.selected.indexOf(item.id);if(selection>=0)card.classList.add('selected');
  const cover=text('div','','music-cover '+(/mondrian/i.test(item.artist)?'mondrian':/morandi/i.test(item.artist)?'morandi':''));
  if(item.image_url){const image=document.createElement('img');image.src=item.image_url;image.alt=item.artwork_title;image.loading='lazy';cover.append(image);}else cover.append(text('span','◒','cover-initial'));
  const select=text('button',selection>=0?String.fromCharCode(65+selection):'+');select.type='button';select.title='Select '+item.name+' for a transition';select.setAttribute('aria-label',select.title);select.setAttribute('aria-pressed',selection>=0?'true':'false');select.disabled=!item.is_loop;select.addEventListener('click',()=>toggleMusic(item.id));cover.append(select);
  const body=text('div','','music-card-body');body.append(text('h3',item.name),text('p',item.artwork_title+' · '+item.artist));const meta=text('div','','card-meta');meta.append(text('span',item.is_loop?'LOOP':'ORIGINAL','tag'),text('span',item.duration.toFixed(2)+' s · WAV'+(item.imported?' · imported':'')));body.append(meta);
  const player=document.createElement('audio');player.controls=true;player.preload='none';player.src=item.audio_url;player.setAttribute('aria-label','Listen to '+item.name);body.append(player);
  const actions=text('div','','card-actions');const rename=text('button','Rename ↗','link-button');rename.addEventListener('click',()=>{state.rename=item.id;$('rename-input').value=item.name;$('rename-dialog').showModal();});const download=text('a','Download ↓','link-button');download.href=item.audio_url+'?download=true';download.download='';actions.append(rename,download);body.append(actions);card.append(cover,body);$('music-library').append(card);
 }
 $('selection-bar').hidden=!state.selected.length;$('selection-label').textContent=state.selected.map((id,index)=>String.fromCharCode(65+index)+': '+(state.library.find(x=>x.id===id)?.name||'')).join('   →   ');$('connect-selected').disabled=state.selected.length!==2;
}
function toggleMusic(id) {if(state.selected.includes(id))state.selected=state.selected.filter(x=>x!==id);else if(state.selected.length<2)state.selected.push(id);else{notify('Two tracks are already selected. Deselect one to choose another.');return;}store('selection',state.selected);renderLibrary();}
async function loadLibrary() {
 state.library=await api('/api/music');state.selected=state.selected.filter(id=>state.library.some(x=>x.id===id));renderLibrary();
 const previous=[$('endpoint-a').value,$('endpoint-b').value];const saved=recall('endpoints',[]);const loops=state.library.filter(x=>x.is_loop);
 for(const [index,side] of ['a','b'].entries()){const select=$('endpoint-'+side);select.replaceChildren(new Option('Choose a saved loop',''));for(const item of loops)select.append(new Option(item.name+' · '+item.duration.toFixed(1)+' s',item.id));const preferred=previous[index]||saved[index];if(loops.some(x=>x.id===preferred))select.value=preferred;}
 syncEndpoints(false);refreshButtons();
}
$('library-search').addEventListener('input',renderLibrary);$('refresh-library').addEventListener('click',()=>loadLibrary().catch(error=>notify(error.message)));
$('clear-selection').addEventListener('click',()=>{state.selected=[];store('selection',[]);renderLibrary();});
$('connect-selected').addEventListener('click',()=>{if(state.selected.length!==2)return;$('endpoint-a').value=state.selected[0];$('endpoint-b').value=state.selected[1];syncEndpoints();go('transition');});
$('close-rename').addEventListener('click',()=>$('rename-dialog').close());
$('rename-form').addEventListener('submit',async event=>{event.preventDefault();try{await api('/api/music/'+state.rename,{name:$('rename-input').value.trim()},'PATCH');$('rename-dialog').close();await loadLibrary();notify('Music name and download filename updated.',true);}catch(error){notify(error.message);}});
function newArtwork() {
 state.artwork=null;state.image=null;state.artworkDirty=false;state.recording=null;state.loop=null;
 for(const id of ['artwork-title','artist','curator-notes','music-prompt'])$(id).value='';
 $('duration').value=32;$('artwork-file').value='';$('image-preview').removeAttribute('src');$('image-preview').hidden=true;$('replace-image').hidden=true;$('upload-placeholder').hidden=false;$('analysis').hidden=true;$('music-result').hidden=true;$('music-empty').hidden=false;
 $('artwork-status').textContent='The image and your notes will guide the interpretation.';
 store('recording',null);store('loop',null);saveDraft();refreshButtons();go('create');$('artwork-title').focus();
}
for(const id of ['new-artwork','library-create'])$(id).addEventListener('click',newArtwork);
for(const id of ['choose-in-library','grid-create'])$(id).addEventListener('click',()=>go('library'));
function syncEndpoints(clearBridge=true) {
 for(const side of ['a','b']){const item=state.library.find(x=>x.id===$('endpoint-'+side).value);const player=$('endpoint-'+side+'-audio');if(item){if(player.getAttribute('src')!==item.audio_url){player.pause();player.src=item.audio_url;}}else{player.pause();player.removeAttribute('src');}}
 store('endpoints',[$('endpoint-a').value,$('endpoint-b').value]);
 if(clearBridge){state.bridge=null;store('bridge',null);$('bridge-preview').hidden=true;}
 updateBridgeDiagram();refreshButtons();
}
for(const side of ['a','b'])$('endpoint-'+side).addEventListener('change',()=>syncEndpoints());
$('swap-endpoints').addEventListener('click',()=>{const a=$('endpoint-a').value;$('endpoint-a').value=$('endpoint-b').value;$('endpoint-b').value=a;syncEndpoints();});
function updateBridgeDiagram() {
 const inpaint=$('grid-method').value==='inpaint';
 $('transition-cost').textContent=inpaint?'Full grid: 3 inpaint requests · no audio-to-audio':'Full grid: 1 inpaint + 2 audio-to-audio generations';
 $('method-description').textContent=inpaint?'Generate the shared middle from A/B, then inpaint A → middle and middle → B using real audio on both sides. Only the masked music is kept for each cell.':'Generate the shared middle with inpainting, then reinterpret it twice with audio-to-audio, guided by the endpoint prompts.';
 $('preview-build-note').textContent='Only this excerpt supplies the center. Building uses '+(inpaint?'2 inpaint':'2 audio-to-audio')+' requests for its neighbors; the bridge is not regenerated. Minimum excerpt: 4 seconds.';
 const context=Number($('bridge-context').value),bridge=Number($('bridge-duration').value);
 for(const side of ['a','b']){const item=state.library.find(x=>x.id===$('endpoint-'+side).value);$('reference-'+side+'-label').textContent=Math.min(context,item?.duration||context).toFixed(1)+' s · reference only';}
 $('generated-middle-label').textContent=bridge+' s · becomes the middle cell';
 store('bridge-settings',{context:$('bridge-context').value,bridge:$('bridge-duration').value,prompt:$('transition-direction').value,name:$('gallery-name').value,method:$('grid-method').value});
}
for(const id of ['bridge-context','bridge-duration','transition-direction','gallery-name','grid-method'])$(id).addEventListener('input',updateBridgeDiagram);
function bridgeValues() {return {a_id:$('endpoint-a').value,b_id:$('endpoint-b').value,context:Number($('bridge-context').value),bridge:Number($('bridge-duration').value),prompt:$('transition-direction').value,name:$('gallery-name').value,method:$('grid-method').value};}
function generateConnection(kind) {for(const id of ['bridge-context','bridge-duration'])if(!$(id).reportValidity())return;startTask(kind,bridgeValues());}
$('preview-bridge').addEventListener('click',()=>generateConnection('bridge'));
$('generate-grid').addEventListener('click',()=>generateConnection('grid'));
$('build-from-bridge').addEventListener('click',()=>{if(!$('middle-start').reportValidity()||!$('middle-end').reportValidity())return;startTask('grid',{...bridgeValues(),source_job_id:state.bridge.id,start:Number($('middle-start').value),end:Number($('middle-end').value)});});

async function loadGrids() {
 state.grids=await api('/api/grids');const previous=state.grid?.id;$('grid-history').replaceChildren(new Option('Choose a saved gallery',''));for(const grid of state.grids)$('grid-history').append(new Option(grid.name,grid.id));$('grid-history').value=previous||'';
}
async function chooseGrid(id) {
 if(!id)return;await stopGrid();state.grid=await api('/api/grids/'+id);store('grid',id);$('grid-empty').hidden=true;$('grid-player').hidden=false;$('grid-title').textContent=state.grid.name;$('grid-history').value=id;$('grid-position').value=2;$('grid-a-name').textContent=state.grid.a_name;$('grid-b-name').textContent=state.grid.b_name;
 $('grid-cells').replaceChildren();$('cell-downloads').replaceChildren();
 for(let i=0;i<5;i++){
  const item=state.grid.files[String(i)];const button=text('button','','grid-cell');button.type='button';button.setAttribute('aria-label','Move to '+item.label);button.append(text('span','0'+(i+1)+' / '+(['ARTWORK A','A-LEANING','SHARED MIDDLE','B-LEANING','ARTWORK B'][i])));const bars=text('div','','cell-bars');for(let k=0;k<9;k++)bars.append(document.createElement('i'));button.append(bars,text('strong',['A','A + middle','Middle','Middle + B','B'][i]),text('small',item.duration.toFixed(2)+' s loop'));button.addEventListener('click',()=>{$('grid-position').value=i;setPosition();});$('grid-cells').append(button);
  const link=text('a','Cell '+(i+1)+' ↓');link.href='/api/grids/'+id+'/audio/'+i+'?download=true';link.download='';$('cell-downloads').append(link);
 }
 const interval=state.grid.middle_interval;$('grid-details').textContent=`The middle uses only ${interval[0].toFixed(2)}–${interval[1].toFixed(2)} s of the inpaint recording. The reference ends are excluded. The three interior cells use a ${state.grid.loop_overlap} s head/tail overlap. ${state.grid.method==='inpaint'?'All three interior cells use inpainting: A → B for the middle, A → middle for cell 2, and middle → B for cell 4. The real audio anchors are removed from every generated cell.':'Cells 2 and 4 are audio-to-audio variations of that middle, guided by each endpoint’s music prompt.'} Playback blends audio; it does not align beats or infer musical compatibility.`;
 setPosition();$('grid-play-status').textContent='Ready. Start listening, then move across the room.';
}
$('grid-history').addEventListener('change',event=>chooseGrid(event.target.value).catch(error=>notify(error.message)));
async function stopGrid() {
 gridPlaying=false;gridLoading=false;for(const node of gridNodes){try{node.source.stop();node.source.disconnect();node.gain.disconnect();}catch{}}gridNodes=[];if(audioContext){const previous=audioContext;audioContext=null;await previous.close().catch(()=>{});}$('grid-play').textContent='Start listening ▶';
}
async function startGrid() {
 if(!state.grid||gridLoading)return;
 if(gridPlaying){await stopGrid();$('grid-play-status').textContent='Playback stopped.';return;}
 gridLoading=true;$('grid-play').disabled=true;$('grid-play-status').textContent='Preparing all five loops…';
 const id=state.grid.id;const context=new (window.AudioContext||window.webkitAudioContext)();audioContext=context;
 try{
  await context.resume();document.querySelectorAll('audio').forEach(player=>player.pause());
  const buffers=await Promise.all(Array.from({length:5},async(_,i)=>{const response=await fetch('/api/grids/'+id+'/audio/'+i);if(!response.ok)throw new Error('A grid cell could not be loaded.');return context.decodeAudioData(await response.arrayBuffer());}));
  if(audioContext!==context||state.grid.id!==id)return;
  const start=context.currentTime+.12;
  gridNodes=buffers.map(buffer=>{const source=context.createBufferSource();source.buffer=buffer;source.loop=true;const gain=context.createGain();gain.gain.value=0;source.connect(gain).connect(context.destination);source.start(start);return {source,gain};});
  gridPlaying=true;gridLoading=false;$('grid-play').textContent='Stop listening ■';setPosition(true);$('grid-play-status').textContent='Playing. Move between neighboring musical states; all five loops keep running.';
 }catch(error){await stopGrid();$('grid-play-status').textContent=error.message||'Playback could not start. Please try again.';}finally{$('grid-play').disabled=false;gridLoading=false;}
}
function setPosition(immediate=false) {
 const position=Number($('grid-position').value),left=Math.floor(position),fraction=position-left;const weights=Array(5).fill(0);weights[left]=Math.cos(fraction*Math.PI/2);if(left<4)weights[left+1]=Math.sin(fraction*Math.PI/2);
 document.querySelectorAll('.grid-cell').forEach((cell,i)=>{cell.style.setProperty('--weight',weights[i]);cell.classList.toggle('active',weights[i]>.05);});
 const labels=['Artwork A','A-leaning','Shared middle','B-leaning','Artwork B'];$('position-label').textContent=Math.abs(position-Math.round(position))<.03?labels[Math.round(position)]:labels[left]+' ↔ '+labels[Math.min(left+1,4)];
 if(gridPlaying&&audioContext){const time=audioContext.currentTime,duration=immediate ? 0.15 : Number($('grid-fade').value);for(let i=0;i<gridNodes.length;i++){const parameter=gridNodes[i].gain.gain;if(parameter.cancelAndHoldAtTime)parameter.cancelAndHoldAtTime(time);else{parameter.cancelScheduledValues(time);parameter.setValueAtTime(parameter.value,time);}parameter.linearRampToValueAtTime(weights[i]*.7,time+duration);}}
}
$('grid-play').addEventListener('click',startGrid);$('grid-position').addEventListener('input',()=>setPosition());$('grid-fade').addEventListener('input',()=>{$('grid-fade-label').textContent=Number($('grid-fade').value).toFixed(1)+' s';});
document.addEventListener('play',event=>{if(event.target.tagName==='AUDIO'){document.querySelectorAll('audio').forEach(player=>{if(player!==event.target)player.pause();});if(gridPlaying)stopGrid();}},true);
window.addEventListener('beforeunload',()=>{if(audioContext)audioContext.close();});

async function initialize() {
 const view=location.hash.slice(1).split('/')[0];showView(['create','library','transition','grid'].includes(view)?view:'create');
 const draft=recall('draft');if(draft){$('artwork-title').value=draft.title||'';$('artist').value=draft.artist||'';$('curator-notes').value=draft.notes||'';$('music-prompt').value=draft.prompt||'';$('duration').value=draft.duration||32;}
 const bridge=recall('bridge-settings');if(bridge){$('bridge-context').value=bridge.context||8;$('bridge-duration').value=bridge.bridge||12;$('transition-direction').value=bridge.prompt||'';$('gallery-name').value=bridge.name||'';$('grid-method').value=bridge.method||'inpaint';}
 try{
  await loadConfig();state.jobs=await api('/api/jobs');await loadLibrary();await loadGrids();renderHistory();
  if(draft?.artworkId){try{state.artwork=await api('/api/artworks/'+draft.artworkId);$('image-preview').src='/api/artworks/'+state.artwork.id+'/image';$('image-preview').hidden=false;$('upload-placeholder').hidden=true;$('replace-image').hidden=false;$('artwork-status').textContent='Saved: '+state.artwork.title+' · '+state.artwork.artist;if(state.artwork.analysis)renderAnalysis(state.artwork.analysis);
   const imageResponse=await fetch('/api/artworks/'+state.artwork.id+'/image');const blob=await imageResponse.blob();state.image=await new Promise(resolve=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.readAsDataURL(blob);});
  }catch{/* A removed draft artwork can be replaced with a fresh upload. */}}
  const savedLoop=recall('loop');const recording=state.jobs.find(x=>x.id===recall('recording')&&x.status==='completed'&&x.kind==='music');if(recording)showRecording(recording);
  const loop=state.jobs.find(x=>x.id===savedLoop&&x.status==='completed'&&x.kind==='loop'&&x.payload.source_job_id===recording?.id);if(loop)showLoop(loop);
  const bridgeJob=state.jobs.find(x=>x.id===recall('bridge')&&x.status==='completed'&&x.kind==='bridge');if(bridgeJob)showBridge(bridgeJob);
  const savedGrid=(view==='grid'?location.hash.slice(1).split('/')[1]:null)||recall('grid')||state.grids[0]?.id;if(savedGrid)await chooseGrid(savedGrid);
  const lastTask=state.jobs.find(x=>x.id===recall('last-task'));if(lastTask?.status==='completed'&&recall('last-applied-task')!==lastTask.id)await completed(lastTask);
  const active=state.jobs.find(x=>!['completed','failed'].includes(x.status));if(active){state.active=active.id;showProgress(active);pollTimer=setTimeout(poll,1000);}
  refreshButtons();
 }catch(error){notify(error.message||'Could not connect. Start the local curator service and refresh.');}
}
initialize();
