// Synthetic browser smoke tests. Every page request is fulfilled or denied through CDP.
import { spawn } from 'node:child_process';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
const root=path.resolve(import.meta.dirname,'..');
const profile=await mkdtemp(path.join(tmpdir(),'rudo-browser-'));
const chrome=process.env.RUDO_TEST_CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const proc=spawn(chrome,['--headless=new','--remote-debugging-pipe','--no-first-run','--disable-background-networking','--disable-component-update','--disable-sync','--disable-default-apps','--no-default-browser-check',`--user-data-dir=${profile}`],{stdio:['ignore','ignore','ignore','pipe','pipe']});
let sequence=0,buffer='',session;
const pending=new Map(),listeners=new Map(),errors=[],calls=[],results=[];
proc.on('error',error=>{for(const entry of pending.values())entry.reject(error);});
function send(method,params={},sid=session){return new Promise((resolve,reject)=>{const id=++sequence;pending.set(id,{resolve,reject});proc.stdio[3].write(JSON.stringify({id,method,params,...(sid?{sessionId:sid}:{})})+'\0');});}
proc.stdio[4].on('data',chunk=>{buffer+=chunk;let pos;while((pos=buffer.indexOf('\0'))>=0){const message=JSON.parse(buffer.slice(0,pos));buffer=buffer.slice(pos+1);if(message.id){const p=pending.get(message.id);pending.delete(message.id);if(p)message.error?p.reject(new Error(message.error.message)):p.resolve(message.result);}else{for(const fn of listeners.get(message.method)||[])Promise.resolve(fn(message.params)).catch(e=>errors.push(String(e)));}}});
function on(event,fn){listeners.set(event,[...(listeners.get(event)||[]),fn]);}
const cid='11111111-1111-4111-8111-111111111111',oid='22222222-2222-4222-8222-222222222222';
const state={status:'active',version:1,orderStatus:'pending',orderVersion:1,messages:[{role:'user',message:'Synthetic greeting',timestamp:'2026-01-01T00:00:00Z'}],firebase:true};
const firebase=`window.syntheticUser={uid:'synthetic',email:'synthetic@example.test',displayName:'Synthetic Staff',getIdToken:async()=> 'synthetic-token'};window.syntheticAuth={currentUser:window.syntheticUser,onAuthStateChanged(callback){setTimeout(()=>callback(this.currentUser),0);},signOut:async function(){this.currentUser=null;}};window.firebase={apps:[],initializeApp(){this.apps.push({});},auth(){return window.syntheticAuth;}};`;
const chart=`window.Chart=class {constructor(ctx,config){Object.assign(this,config);}update(){}destroy(){}};`;
async function intercept({requestId,request}){
 const url=new URL(request.url),pathname=url.pathname;calls.push({host:url.hostname,path:pathname,method:request.method});
 async function fulfil(body,type='application/json',status=200){await send('Fetch.fulfillRequest',{requestId,responseCode:status,responseHeaders:[{name:'Content-Type',value:type}],body:Buffer.from(typeof body==='string'?body:JSON.stringify(body)).toString('base64')});}
 if(url.hostname==='www.gstatic.com'){await fulfil(state.firebase&&pathname.includes('firebase-app-')?firebase:'','application/javascript');return;}
 if(url.hostname==='cdn.jsdelivr.net'){await fulfil(chart,'application/javascript');return;}
 if(url.hostname!=='rudo.test'){await send('Fetch.failRequest',{requestId,errorReason:'BlockedByClient'});return;}
 const thread=()=>({id:cid,phone:'260000000001',status:state.status,version:state.version,messages:state.messages});
 const order=()=>({id:oid,status:state.orderStatus,version:state.orderVersion,payload:{product:'Synthetic product',price:'12.50'},created_at:'2026-01-01T00:00:00Z'});
 if(pathname.startsWith('/api/')){
  const auth=Object.entries(request.headers).find(([key])=>key.toLowerCase()==='authorization')?.[1];assert.equal(auth,'Bearer synthetic-token');
  if(pathname==='/api/me'){await fulfil({role:'operator',facilities:['clinic-a']});return;}
  if(pathname==='/api/conversations'){await fulfil({items:[thread()]});return;}
  if(pathname===`/api/conversations/${cid}/messages`){state.messages.push({role:'bot',message:JSON.parse(request.postData).message,delivery_status:'pending',timestamp:'2026-01-01T00:00:01Z'});await fulfil({id:crypto.randomUUID(),status:'pending'},'application/json',202);return;}
  if(pathname===`/api/conversations/${cid}`){if(request.method==='PATCH'){state.status='closed';state.version++;}await fulfil(thread());return;}
  if(pathname==='/api/orders'){await fulfil({items:[order()]});return;}
  if(pathname===`/api/orders/${oid}`){state.orderStatus=JSON.parse(request.postData).status;state.orderVersion++;await fulfil(order());return;}
  if(pathname==='/api/qr-analytics'){await fulfil({totalRecords:0,counts:Object.fromEntries(['Mandebvu Clinic','Avondale Clinic','Mandebvu Pharmacy',"N'gombe Clinic",'Chelstone Clinic'].map(n=>[n,{'Poster 1':0,'Poster 2':0,Flyer:0}]))});return;}
  await fulfil({error:'unexpected_synthetic_endpoint'},'application/json',500);return;
 }
 const file=path.resolve(root,'.'+pathname);
 if(!file.startsWith(root+path.sep)){await fulfil('','text/plain',404);return;}
 try {const body=await readFile(file);const mime={'.html':'text/html','.js':'application/javascript','.css':'text/css','.png':'image/png','.jpg':'image/jpeg','.ico':'image/x-icon'}[path.extname(file)];if(!mime)throw Error();await send('Fetch.fulfillRequest',{requestId,responseCode:200,responseHeaders:[{name:'Content-Type',value:mime}],body:body.toString('base64')});}
 catch {await fulfil('','text/plain',404);}
}
async function evaluate(expression){const r=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw new Error(r.exceptionDetails.text+': '+r.exceptionDetails.exception?.description);return r.result?.value;}
async function until(expression){for(let i=0;i<100;i++){if(await evaluate(expression))return;await new Promise(r=>setTimeout(r,50));}throw new Error('Browser condition timed out: '+expression);}
async function navigate(filename){await send('Page.navigate',{url:'https://rudo.test/'+filename});await until(`document.readyState==='complete' && location.pathname.endsWith(${JSON.stringify(filename)})`);}
const deadline=setTimeout(()=>{proc.kill('SIGKILL');console.error('Browser smoke timeout');process.exitCode=1;},45000);
try{
 const {targetId}=await send('Target.createTarget',{url:'about:blank'},null);session=(await send('Target.attachToTarget',{targetId,flatten:true},null)).sessionId;
 await send('Page.enable');await send('Runtime.enable');await send('Fetch.enable',{patterns:[{urlPattern:'*'}]});
 on('Fetch.requestPaused',intercept);on('Runtime.exceptionThrown',event=>errors.push(event.exceptionDetails.exception?.description||event.exceptionDetails.text));
 await navigate('chats.html');await until("!document.getElementById('chatInput').disabled");
 await evaluate("document.getElementById('chatInput').value='Synthetic outbound'; document.getElementById('sendBtn').click()");
 await until("document.getElementById('chatMain').textContent.includes('Synthetic outbound')");assert.equal(state.messages.at(-1).delivery_status,'pending');results.push('chat load and queued send');
 await evaluate("document.getElementById('resolveButton').click()");await until("document.getElementById('chatStatusBadge').textContent==='Closed thread'");assert.equal(state.status,'closed');results.push('persisted resolution');
 await navigate('orders.html');await until("document.getElementById('ordersContainer').textContent.includes('Synthetic product')");
 await evaluate("document.querySelector('#ordersContainer select').value='paid'; document.querySelector('#ordersContainer button').click()");
 await until("document.getElementById('ordersState').textContent.includes('saved')");assert.equal(state.orderStatus,'paid');results.push('order update');
 await navigate('index2.html');await until("document.getElementById('lastSync').textContent.includes('Updated')");assert.equal(await evaluate("document.getElementById('liveConversations').textContent"),'1');results.push('dashboard metrics');
 await navigate('analytics.html');await until("document.querySelector('#qrLastUpdated')?.textContent.includes('Updated')");results.push('analytics and referrals');
 assert.deepEqual(errors,[]);assert(!calls.some(c=>c.host.includes('upstash')||c.host.includes('facebook')));results.push('no page errors or privileged provider calls');
 state.firebase=false;const count=calls.filter(c=>c.path.startsWith('/api/')).length;
 await send('Page.addScriptToEvaluateOnNewDocument',{source:"localStorage.setItem('rudoSessionActive','true')"});
 await send('Page.navigate',{url:'https://rudo.test/chats.html'});await until("location.pathname==='/login.html' && document.readyState==='complete'");
 assert.equal(calls.filter(c=>c.path.startsWith('/api/')).length,count);results.push('forged session denied before data requests');
 console.log(JSON.stringify({passed:results.length,checks:results,pageErrors:errors},null,2));
}catch(error){console.error(error.stack);console.error('Page errors:',JSON.stringify(errors));process.exitCode=1;}
finally{clearTimeout(deadline);proc.kill('SIGTERM');await new Promise(r=>setTimeout(r,300));await rm(profile,{recursive:true,force:true});}
