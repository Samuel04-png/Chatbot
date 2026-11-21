// Real Chrome -> Flask (IPC) -> restricted PostgreSQL, with Supabase JS replaced by an offline fake SDK.
// Exercises staff-login/staff-reset pages and the observer in Supabase browser-auth mode.
import { spawn } from 'node:child_process';
import { mkdtemp,rm,writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import readline from 'node:readline';
import assert from 'node:assert/strict';
const LINKED=process.env.RUDO_LINKED_UUID,PENDING=process.env.RUDO_PENDING_UUID,ORIGIN='http://127.0.0.1:5051';
const SDK_URL='https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.45.4/dist/umd/supabase.js';
const FAKE_SDK=`window.supabase={createClient(url,key,opts){
 window.__sbCreate={url,key,flow:opts.auth.flowType,storageKey:opts.auth.storageKey};
 const listeners=[],read=()=>JSON.parse(sessionStorage.getItem('fake-sb')||'null');
 const log=c=>{const v=JSON.parse(sessionStorage.getItem('fake-sb-calls')||'[]');v.push(c);sessionStorage.setItem('fake-sb-calls',JSON.stringify(v));};
 const write=s=>{s?sessionStorage.setItem('fake-sb',JSON.stringify(s)):sessionStorage.removeItem('fake-sb');listeners.forEach(f=>f(s?'SIGNED_IN':'SIGNED_OUT',s));};
 const accounts={'staff@example.test':'${LINKED}','pending@example.test':'${PENDING}'};
 return {auth:{
  async getSession(){return {data:{session:read()},error:null};},
  onAuthStateChange(f){listeners.push(f);return {data:{subscription:{unsubscribe(){}}}};},
  async signInWithPassword({email,password}){log('password');const id=accounts[email];if(!id||password!=='Correct-password-1')return {error:{code:'invalid_credentials',status:400}};write({access_token:'sb:'+id,user:{id,email}});return {error:null};},
  async signInWithOAuth(o){log('oauth:'+o.provider+':'+o.options.redirectTo);return {error:null};},
  async signUp(o){log('signup:'+o.email+':'+o.options.emailRedirectTo);return {error:null};},
  async resetPasswordForEmail(email,o){log('reset:'+o.redirectTo);return {error:null};},
  async updateUser(o){log('update:'+(o.password.length>=12));return {error:null};},
  async signOut(o){log('signout:'+(o?.scope||'local'));if(o?.scope!=='others')write(null);return {error:null};}
 }};
}};`;
const profile=await mkdtemp(path.join(tmpdir(),'rudo-supabase-browser-'));
const chrome=process.env.RUDO_TEST_CHROME||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const proc=spawn(chrome,['--headless=new','--remote-debugging-pipe','--no-first-run','--disable-background-networking','--disable-component-update','--disable-sync','--disable-default-apps',`--user-data-dir=${profile}`],{stdio:['ignore','ignore','ignore','pipe','pipe']});
let seq=0,buffer='',session,bridgeSeq=0;
const pending=new Map(),events=new Map(),bridgePending=new Map(),errors=[],external=[],checks=[];
const input=readline.createInterface({input:process.stdin});
input.on('line',line=>{const value=JSON.parse(line),p=bridgePending.get(value.id);if(p){bridgePending.delete(value.id);p.resolve(value);}});
function bridge(data){return new Promise(resolve=>{const id=++bridgeSeq;bridgePending.set(id,{resolve});process.stdout.write(JSON.stringify({id,...data})+'\n');});}
function send(method,params={},sid=session){return new Promise((resolve,reject)=>{const id=++seq;pending.set(id,{resolve,reject});proc.stdio[3].write(JSON.stringify({id,method,params,...(sid?{sessionId:sid}:{})})+'\0');});}
proc.stdio[4].on('data',data=>{buffer+=data;let i;while((i=buffer.indexOf('\0'))>=0){const m=JSON.parse(buffer.slice(0,i));buffer=buffer.slice(i+1);if(m.id){const p=pending.get(m.id);pending.delete(m.id);if(p)m.error?p.reject(new Error(m.error.message)):p.resolve(m.result);}else for(const fn of events.get(m.method)||[])Promise.resolve(fn(m.params)).catch(e=>errors.push(String(e)));}});
function on(name,fn){events.set(name,[...(events.get(name)||[]),fn]);}
async function evaluate(expression){const r=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text);return r.result?.value;}
async function wait(expression){for(let i=0;i<200;i++){try{if(await evaluate(expression))return;}catch{}await new Promise(r=>setTimeout(r,30));}throw Error('Browser condition timed out: '+expression);}
const calls=()=>evaluate("JSON.parse(sessionStorage.getItem('fake-sb-calls')||'[]')");
const fill=(id,value)=>evaluate(`document.getElementById('${id}').value=${JSON.stringify(value)}`);
const submit=id=>evaluate(`document.getElementById('${id}').requestSubmit()`);
const stateIs=(text,cls)=>wait(`document.getElementById('state').textContent.includes(${JSON.stringify(text)}) && document.getElementById('state').className===${JSON.stringify(cls)}`);
const deadline=setTimeout(()=>{proc.kill('SIGKILL');process.exit(1);},90000);
try{
 const target=await send('Target.createTarget',{url:'about:blank'},null);session=(await send('Target.attachToTarget',{targetId:target.targetId,flatten:true},null)).sessionId;
 await send('Page.enable');await send('Runtime.enable');await send('Emulation.setDeviceMetricsOverride',{width:1280,height:900,deviceScaleFactor:1,mobile:false});
 on('Runtime.exceptionThrown',e=>errors.push(e.exceptionDetails.exception?.description||e.exceptionDetails.text));
 on('Fetch.requestPaused',async ({requestId,request})=>{
  const url=new URL(request.url);
  if(request.url===SDK_URL){await send('Fetch.fulfillRequest',{requestId,responseCode:200,responseHeaders:[{name:'Content-Type',value:'text/javascript'}],body:Buffer.from(FAKE_SDK).toString('base64')});return;}
  if(url.origin!==ORIGIN){external.push(url.origin);await send('Fetch.failRequest',{requestId,errorReason:'BlockedByClient'});return;}
  const r=await bridge({request:{url:url.pathname+url.search,method:request.method,headers:request.headers,body:request.postData||null}});
  await send('Fetch.fulfillRequest',{requestId,responseCode:r.status,responseHeaders:Object.entries(r.headers).map(([name,value])=>({name,value})),body:r.body});
 });
 await send('Fetch.enable',{patterns:[{urlPattern:'*'}]});
 await send('Page.navigate',{url:ORIGIN+'/observer.html#orders'});
 await wait("location.pathname==='/staff-login.html' && !document.getElementById('signin').hidden");
 assert.deepEqual(await evaluate('window.__sbCreate'),{url:'https://synthetic-ref.supabase.co',key:'sb_publishable_synthetic',flow:'pkce',storageKey:'rudo-staff-auth'});
 checks.push('signed-out observer redirects to Supabase staff sign-in; browser receives only the publishable key; PKCE flow');
 assert(!await evaluate("document.getElementById('google').hidden"));await evaluate("document.getElementById('google').click()");
 await wait("JSON.parse(sessionStorage.getItem('fake-sb-calls')||'[]').includes('oauth:google:"+ORIGIN+"/staff-login.html')");checks.push('Google sign-in starts OAuth with a same-origin return URL');
 await fill('email','staff@example.test');await fill('password','wrong-password');await submit('signin');
 await stateIs('The email or password is incorrect.','error');checks.push('wrong password shows a non-enumerating error');
 await evaluate("document.getElementById('show-request').click()");await fill('request-email','new@example.test');await fill('request-password','short');
 await evaluate("document.querySelector('#request button[type=submit]').click()");await new Promise(r=>setTimeout(r,150));
 assert(!(await calls()).some(c=>c.startsWith('signup:')));
 await fill('request-password','Long-enough-password');await submit('request');
 await stateIs('wait for an administrator to approve access','ok');
 assert((await calls()).includes('signup:new@example.test:'+ORIGIN+'/staff-login.html'));checks.push('short password blocked before sign-up; request-access explains pending approval');
 await fill('email','pending@example.test');await fill('password','Correct-password-1');await submit('signin');
 await wait("location.pathname==='/observer.html' && document.getElementById('page-state').textContent.includes('pending administrator approval')");
 assert(await evaluate("document.getElementById('page-state').classList.contains('error') && document.getElementById('records').children.length===0"));
 checks.push('unapproved Supabase login sees pending-approval state and no records');
 await evaluate("document.getElementById('logout').click()");await wait("location.pathname==='/staff-login.html' && !document.getElementById('signin').hidden");
 assert.equal(await evaluate("sessionStorage.getItem('fake-sb')"),null);checks.push('sign-out clears the session and returns to sign-in');
 await fill('email','staff@example.test');await fill('password','Correct-password-1');await submit('signin');
 await wait("location.pathname==='/observer.html' && document.querySelectorAll('.conversation-card').length===3");
 assert(await evaluate("document.getElementById('identity').textContent.includes('operator')"));checks.push('linked Supabase login inherits the operator role and facility-scoped conversations');
 await evaluate("location.hash='orders'");await wait("document.querySelector('#records h3')?.textContent.startsWith('Order ')");checks.push('linked login reads scoped orders');
 await send('Page.navigate',{url:ORIGIN+'/staff-reset.html'});await wait("!document.getElementById('reset-request').hidden");
 await fill('reset-email','anyone@example.test');await submit('reset-request');await stateIs('If that email belongs to a staff account','ok');
 assert((await calls()).includes('reset:'+ORIGIN+'/staff-reset.html?mode=update'));checks.push('password reset request is non-enumerating with same-origin recovery link');
 await evaluate("sessionStorage.removeItem('fake-sb')");await send('Page.navigate',{url:ORIGIN+'/staff-reset.html?mode=update'});
 await stateIs('invalid or has expired','error');checks.push('expired or invalid recovery link is explained');
 await evaluate(`sessionStorage.setItem('fake-sb',JSON.stringify({access_token:'sb:${LINKED}',user:{id:'${LINKED}'}}))`);
 await send('Page.navigate',{url:ORIGIN+'/staff-reset.html?mode=update'});await wait("!document.getElementById('reset-update').hidden");
 await fill('new-password','New-password-123');await fill('confirm-password','Different-123456');await submit('reset-update');await stateIs('do not match','error');
 await fill('confirm-password','New-password-123');await submit('reset-update');await stateIs('Password updated','ok');
 const after=await calls();assert(after.includes('update:true')&&after.includes('signout:others'));checks.push('recovery sets a new password and signs out other sessions');
 const config=await evaluate("fetch('/api/auth-config').then(r=>r.text())");assert(!/secret|service/i.test(config));checks.push('auth-config response contains no privileged key');
 await evaluate("sessionStorage.removeItem('fake-sb')");await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
 await send('Page.navigate',{url:ORIGIN+'/staff-login.html'});await wait("location.pathname==='/staff-login.html' && !document.getElementById('signin').hidden");assert(await evaluate("document.documentElement.scrollWidth<=window.innerWidth"));
 const shot=await send('Page.captureScreenshot',{format:'png'});await writeFile('.local/staff-login-mobile.png',Buffer.from(shot.data,'base64'));checks.push('sign-in page fits a phone width');
 assert.deepEqual(errors,[]);assert(!external.some(o=>o.includes('gstatic')||o.includes('supabase.co')));checks.push('no page exceptions; no Firebase or live Supabase requests');
 process.stdout.write(JSON.stringify({result:{passed:checks.length,checks,pageErrors:errors,blockedExternalOrigins:[...new Set(external)]}})+'\n');
}catch(e){process.stdout.write(JSON.stringify({failure:e.stack,pageErrors:errors})+'\n');process.exitCode=1;}
finally{clearTimeout(deadline);input.close();proc.kill('SIGTERM');await new Promise(r=>setTimeout(r,200));await rm(profile,{recursive:true,force:true});}
