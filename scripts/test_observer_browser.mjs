// True browser -> Flask test-client IPC -> restricted PostgreSQL adapter. Every page request is intercepted.
import { spawn } from 'node:child_process';
import { mkdtemp,rm,writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import readline from 'node:readline';
import assert from 'node:assert/strict';
const profile=await mkdtemp(path.join(tmpdir(),'rudo-observer-browser-'));
const chrome=process.env.RUDO_TEST_CHROME||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const proc=spawn(chrome,['--headless=new','--remote-debugging-pipe','--no-first-run','--disable-background-networking','--disable-component-update','--disable-sync','--disable-default-apps',`--user-data-dir=${profile}`],{stdio:['ignore','ignore','ignore','pipe','pipe']});
let seq=0,buffer='',session,bridgeSeq=0,hold=false,held=null;
const pending=new Map(),events=new Map(),bridgePending=new Map(),errors=[],requests=[],checks=[];
const input=readline.createInterface({input:process.stdin});
input.on('line',line=>{const value=JSON.parse(line),p=bridgePending.get(value.id);if(p){bridgePending.delete(value.id);p.resolve(value);}});
function bridge(data){return new Promise((resolve,reject)=>{const id=++bridgeSeq;bridgePending.set(id,{resolve,reject});process.stdout.write(JSON.stringify({id,...data})+'\n');});}
function send(method,params={},sid=session){return new Promise((resolve,reject)=>{const id=++seq;pending.set(id,{resolve,reject});proc.stdio[3].write(JSON.stringify({id,method,params,...(sid?{sessionId:sid}:{})})+'\0');});}
proc.stdio[4].on('data',data=>{buffer+=data;let i;while((i=buffer.indexOf('\0'))>=0){const m=JSON.parse(buffer.slice(0,i));buffer=buffer.slice(i+1);if(m.id){const p=pending.get(m.id);pending.delete(m.id);if(p)m.error?p.reject(new Error(m.error.message)):p.resolve(m.result);}else for(const fn of events.get(m.method)||[])Promise.resolve(fn(m.params)).catch(e=>errors.push(String(e)));}});
function on(name,fn){events.set(name,[...(events.get(name)||[]),fn]);}
async function evaluate(expression){const r=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text);return r.result?.value;}
async function wait(expression){for(let i=0;i<150;i++){if(await evaluate(expression))return;await new Promise(r=>setTimeout(r,30));}throw Error('Browser condition timed out: '+expression);}
async function waitNode(predicate){for(let i=0;i<150;i++){if(predicate())return;await new Promise(r=>setTimeout(r,30));}throw Error('IPC condition timed out');}
async function fulfill(requestId,response){await send('Fetch.fulfillRequest',{requestId,responseCode:response.status,responseHeaders:Object.entries(response.headers).map(([name,value])=>({name,value})),body:response.body});}
const deadline=setTimeout(()=>{proc.kill('SIGKILL');process.exit(1);},60000);
try{
 const target=await send('Target.createTarget',{url:'about:blank'},null);session=(await send('Target.attachToTarget',{targetId:target.targetId,flatten:true},null)).sessionId;
 await send('Page.enable');await send('Runtime.enable');await send('Emulation.setDeviceMetricsOverride',{width:1280,height:900,deviceScaleFactor:1,mobile:false});
 on('Runtime.exceptionThrown',e=>errors.push(e.exceptionDetails.exception?.description||e.exceptionDetails.text));
 on('Fetch.requestPaused',async ({requestId,request})=>{
  const url=new URL(request.url);requests.push({method:request.method,path:url.pathname});
  if(url.origin!=='http://127.0.0.1:5051'){await send('Fetch.failRequest',{requestId,errorReason:'BlockedByClient'});return;}
  const response=await bridge({request:{url:url.pathname+url.search,method:request.method,headers:request.headers,body:request.postData||null}});
  if(hold&&url.pathname.startsWith('/api/conversations/')){hold=false;held={requestId,response};return;}
  await fulfill(requestId,response);
 });
 await send('Fetch.enable',{patterns:[{urlPattern:'*'}]});
 await send('Page.navigate',{url:'http://127.0.0.1:5051/observer.html'});
 await wait("document.querySelectorAll('.conversation-card').length===3");
 assert.equal(requests.filter(r=>/^\/api\/conversations\//.test(r.path)).length,0);checks.push('bounded summary load; history not eagerly fetched');
 assert(await evaluate("document.body.textContent.includes('Read-only observer') && document.body.textContent.includes('Synthetic local environment')"));
 assert.equal(await evaluate("document.querySelectorAll('#chatInput,#sendBtn,#resolveButton,#ordersContainer select').length"),0);checks.push('read-only controls and synthetic-source labels');
 await evaluate("document.querySelector('.conversation-card').click()");await wait("document.querySelectorAll('.message').length===3");
 assert(await evaluate("document.querySelector('[data-source-id=\"9007199254740993\"]')!==null"));
 assert(await evaluate("[...document.querySelectorAll('.message small')].every(n=>n.textContent.includes('Delivery unknown'))"));checks.push('on-demand source bigint IDs, roles, timestamps and unknown delivery');
 await bridge({control:'source_write'});await evaluate("document.getElementById('thread-refresh').click()");await wait("document.getElementById('messages').textContent.includes('Synthetic fixed answer for browser source update')");checks.push('synthetic bot writes visible after explicit history refresh');
 await bridge({control:'bulk_history'});await evaluate("document.getElementById('thread-refresh').click()");await wait("document.querySelectorAll('.message').length===50 && !document.getElementById('older').hidden");
 await evaluate("document.getElementById('older').click()");await wait("document.querySelectorAll('.message').length===65");
 assert(await evaluate("new Set([...document.querySelectorAll('.message')].map(n=>n.dataset.sourceId)).size===65"));checks.push('bounded older-history pagination without duplicate IDs');
 const shot=await send('Page.captureScreenshot',{format:'png'});await writeFile('.local/observer-browser.png',Buffer.from(shot.data,'base64'));
 await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
 assert(await evaluate("document.documentElement.scrollWidth<=window.innerWidth && document.getElementById('thread').getBoundingClientRect().width<=window.innerWidth"));
 const mobileShot=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:true});await writeFile('.local/observer-mobile.png',Buffer.from(mobileShot.data,'base64'));
 await send('Emulation.setDeviceMetricsOverride',{width:1280,height:900,deviceScaleFactor:1,mobile:false});checks.push('mobile conversation and history layout without horizontal page overflow');
 await evaluate("document.getElementById('search').value='SYN-a'; document.getElementById('filters').requestSubmit()");await wait("document.querySelectorAll('.conversation-card').length===1");checks.push('identifier search and source filters');
 await evaluate("location.hash='orders'");await wait("document.querySelector('#records h3')?.textContent.startsWith('Order ')");
 assert(await evaluate("document.getElementById('records').textContent.includes('Unknown / not recorded')"));checks.push('source-shaped read-only orders with nullable price');
 await evaluate("location.hash='referrals'");await wait("document.getElementById('records').textContent.includes('Synthetic a Poster 2')");checks.push('scoped source referrals, attribution and timestamps');
 await evaluate("location.hash='analytics'");await wait("document.querySelectorAll('.metric').length===5");
 assert(await evaluate("document.getElementById('records').textContent.includes('unavailable from these source fields')"));checks.push('only source-supported analytics');
 const denied=await evaluate("(async()=>{try{await RudoApi.request('/api/conversations',{method:'POST',body:'{}'});}catch(e){return e.status;}})()");assert.equal(denied,405);checks.push('manual hidden mutation request rejected by server');
 await bridge({control:'source_down'});await evaluate("document.getElementById('refresh').click()");await wait("document.getElementById('page-state').classList.contains('error')");
 assert.equal(await evaluate("document.getElementById('records').children.length"),0);await bridge({control:'writer_during_outage'});await bridge({control:'source_up'});
 await evaluate("document.getElementById('refresh').click()");await wait("document.querySelectorAll('.metric').length===5");checks.push('source outage clears stale records; independent bot continues; recovery works');
 await evaluate("location.hash='conversations'");await wait("document.querySelectorAll('.conversation-card').length===1");await evaluate("document.querySelector('.conversation-card').click()");await wait("document.querySelectorAll('.message').length===50");
 hold=true;await evaluate("document.getElementById('thread-refresh').click()");await waitNode(()=>held!==null);
 await evaluate("syntheticSwitchIdentity('other')");await wait("document.getElementById('identity').textContent.includes('other · operator') && document.getElementById('page-state').textContent.includes('Source records loaded')");
 if(held){try{await fulfill(held.requestId,held.response);}catch{}held=null;}
 assert(await evaluate("!document.getElementById('messages').textContent.includes('Synthetic inbound one')"));
 await evaluate("document.getElementById('search').value=''; document.getElementById('filters').requestSubmit()");await wait("document.getElementById('records').textContent.includes('Other facility sentinel')");checks.push('account switch clears cached data and discards delayed prior-user response');
 await evaluate("syntheticSwitchIdentity('empty')");await wait("document.getElementById('page-state').textContent.includes('No authorized source records')");assert(!await evaluate("document.getElementById('page-state').classList.contains('error')"));checks.push('authorized empty dataset is distinct from failure');
 await evaluate("syntheticSwitchIdentity('analyst')");await wait("document.querySelectorAll('.metric').length===5 && document.getElementById('identity').textContent.includes('analyst')");
 assert(await evaluate("[...document.querySelectorAll('[data-view]')].filter(n=>!n.hidden).map(n=>n.dataset.view).join(',')==='analytics'"));checks.push('analyst aggregate-only navigation');
 await evaluate("syntheticSwitchIdentity('revoked')");await wait("document.getElementById('page-state').classList.contains('error')");assert.equal(await evaluate("document.getElementById('records').children.length"),0);checks.push('revoked identity clears records and is rejected');
 assert.deepEqual(errors,[]);checks.push('no page exceptions or real provider calls');
 process.stdout.write(JSON.stringify({result:{passed:checks.length,checks,pageErrors:errors}})+'\n');
}catch(e){process.stdout.write(JSON.stringify({failure:e.stack,pageErrors:errors})+'\n');process.exitCode=1;}
finally{clearTimeout(deadline);input.close();proc.kill('SIGTERM');await new Promise(r=>setTimeout(r,200));await rm(profile,{recursive:true,force:true});}
