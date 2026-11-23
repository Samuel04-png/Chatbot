// Release 1 sign-in path: real login/forgot-password pages with an offline fake Firebase SDK ->
// Flask -> restricted PostgreSQL; staff invitation and approval through the real staff page.
import assert from 'node:assert/strict';
import { writeFile } from 'node:fs/promises';
import { startBrowser } from './browser_harness.mjs';
const FAKE_FIREBASE = `(()=>{const KEY='fake-fb',listeners=[];const read=()=>JSON.parse(sessionStorage.getItem(KEY)||'null');
const log=c=>{const v=JSON.parse(sessionStorage.getItem('fake-fb-calls')||'[]');v.push(c);sessionStorage.setItem('fake-fb-calls',JSON.stringify(v));};
const make=u=>u&&{uid:u.uid,email:u.email,displayName:null,photoURL:null,getIdToken:async()=>'synthetic:'+u.uid,delete:async()=>{}};
const accounts={'admin@example.test':'admin','newbie@example.test':'newbie','operator@example.test':'operator'};
const set=u=>{u?sessionStorage.setItem(KEY,JSON.stringify(u)):sessionStorage.removeItem(KEY);listeners.forEach(f=>f(make(u)));};
const auth={get currentUser(){return make(read())},onAuthStateChanged(cb,err){listeners.push(cb);setTimeout(()=>cb(make(read())),0);return()=>{}},
 async signInWithEmailAndPassword(e,p){log('password');if(!accounts[e]||p!=='Correct-password-1'){const x=new Error('bad');x.code='auth/invalid-login-credentials';throw x;}set({uid:accounts[e],email:e});return {user:make(read())};},
 async signInWithPopup(){log('google');set({uid:'admin',email:'admin@example.test'});return {user:make(read())};},
 async sendPasswordResetEmail(e){log('reset:'+e);},async signOut(){log('signout');set(null);}};
const authFn=()=>auth;authFn.GoogleAuthProvider=function(){};
window.firebase={apps:[],initializeApp(c){this.apps.push(c);window.__fbConfig=c;},auth:authFn};})();`;
const b = await startBrowser({
  'https://www.gstatic.com/firebasejs/9.6.0/firebase-app-compat.js': FAKE_FIREBASE,
  'https://www.gstatic.com/firebasejs/9.6.0/firebase-auth-compat.js': ''
});
const checks = [];
const calls = () => b.evaluate("JSON.parse(sessionStorage.getItem('fake-fb-calls')||'[]')");
const value = (id, v) => b.evaluate(`document.getElementById('${id}').value=${JSON.stringify(v)}`);
async function signIn(email) {
  await b.navigate('/login.html'); await b.wait("document.getElementById('loginForm')!==null && window.firebase?.apps.length>0", 'login page');
  await value('email', email); await value('password', 'Correct-password-1');
  await b.evaluate("document.getElementById('loginForm').requestSubmit()");
}
async function signOut() { await b.evaluate("document.getElementById('logout').click()"); await b.wait("location.pathname==='/login.html'", 'signed out'); }
const deadline = setTimeout(() => process.exit(1), 120000);
try {
  await b.navigate('/observer.html#orders');
  await b.wait("location.pathname==='/login.html' && window.firebase?.apps.length>0", 'redirect to login');
  assert.equal(await b.evaluate("sessionStorage.getItem('rudoRedirectAfterLogin')"), 'observer.html#orders');
  assert.equal(await b.evaluate('window.__fbConfig.projectId'), 'dawa-ca263');
  checks.push('signed-out dashboard visit redirects to Firebase sign-in and remembers the view');
  await value('email', 'admin@example.test'); await value('password', 'wrong');
  await b.evaluate("document.getElementById('loginForm').requestSubmit()");
  await b.wait("document.getElementById('loginMessage').textContent.includes('incorrect')", 'wrong password message');
  checks.push('wrong password shows a non-enumerating error');
  await value('password', 'Correct-password-1'); await b.evaluate("document.getElementById('loginForm').requestSubmit()");
  await b.wait("location.pathname==='/observer.html' && location.hash==='#orders' && document.querySelector('#records h3')?.textContent.startsWith('Order ')", 'admin orders');
  checks.push('Firebase email/password sign-in returns to the requested dashboard view');
  await b.evaluate("location.hash='conversations'"); await b.wait("document.querySelectorAll('.conversation-card').length===5", 'admin conversations');
  assert(!(await b.evaluate("document.getElementById('staff-link').hidden")));
  assert(await b.evaluate("document.getElementById('identity').textContent.includes('Synthetic admin · admin')"));
  checks.push('admin sees facility-scoped conversations and the Staff link');
  await b.evaluate("document.getElementById('staff-link').click()");
  await b.wait("location.pathname==='/staff.html' && !document.getElementById('admin').hidden && document.querySelectorAll('#staff .row').length===7", 'staff page');
  await value('invite-email', 'newbie@example.test'); await value('invite-role', 'operator');
  await b.evaluate("[...document.querySelectorAll('#invite-facilities input')].find(i=>i.dataset.facility==='facility-b' && i.dataset.account==='account-one').click()");
  await b.evaluate("document.getElementById('invite').requestSubmit()");
  await b.wait("document.getElementById('page-state').textContent.includes('Invitation created for newbie@example.test')", 'invitation');
  assert(await b.evaluate("document.getElementById('invitations').textContent.includes('newbie@example.test') && document.getElementById('invitations').textContent.includes('Facility B')"));
  checks.push('admin invites a new operator for one facility');
  await signOut(); await signIn('newbie@example.test');
  await b.wait("['/observer.html','/index2.html'].includes(location.pathname) && document.getElementById('page-state').textContent.includes('pending administrator approval')", 'pending');
  assert.equal(await b.evaluate("document.getElementById('records').children.length"), 0);
  assert(await b.evaluate("document.getElementById('staff-link').hidden"));
  checks.push('invited person signs in and sees pending approval with no records');
  await signOut(); await signIn('admin@example.test');
  await b.wait("['/observer.html','/index2.html'].includes(location.pathname) && document.querySelectorAll('.conversation-card').length===5", 'admin back');
  await b.navigate('/staff.html'); await b.wait("document.getElementById('requests').textContent.includes('newbie@example.test')", 'request listed');
  assert(await b.evaluate("document.getElementById('requests').textContent.includes('email verified')"));
  await b.evaluate("[...document.querySelectorAll('#requests button')].find(x=>x.textContent.startsWith('Approve')).click()");
  await b.wait("document.getElementById('page-state').textContent.includes('newbie@example.test approved') && document.querySelectorAll('#staff .row').length===8", 'approved');
  checks.push('admin approves the verified sign-in against the invitation');
  await signOut(); await signIn('newbie@example.test');
  await b.wait("['/observer.html','/index2.html'].includes(location.pathname) && document.querySelectorAll('.conversation-card').length===1", 'newbie access');
  assert(await b.evaluate("document.getElementById('records').textContent.includes('260000000102')"));
  await b.navigate('/staff.html'); await b.wait("document.getElementById('page-state').textContent.includes('Only admins')", 'non-admin staff page');
  checks.push('approved operator sees only their facility; staff page refuses non-admins');
  await b.navigate('/observer.html'); await b.wait("document.querySelectorAll('.conversation-card').length===1", 'back');
  await signOut(); await b.navigate('/forgot-password.html'); await b.wait("document.getElementById('forgotPasswordForm')!==null && window.firebase?.apps.length>0", 'forgot page');
  await value('email', 'newbie@example.test'); await b.evaluate("document.getElementById('forgotPasswordForm').requestSubmit()");
  await b.wait("document.getElementById('forgotMessage').textContent.includes('Reset email sent')", 'reset');
  assert((await calls()).includes('reset:newbie@example.test'));
  checks.push('Firebase password reset request');
  await b.navigate('/login.html'); await b.wait("window.firebase?.apps.length>0", 'login');
  await b.evaluate("document.getElementById('googleSignIn').click()");
  await b.wait("['/observer.html','/index2.html'].includes(location.pathname) && document.querySelectorAll('.conversation-card').length===5", 'google');
  checks.push('Google sign-in path');
  await b.evaluate("[...document.querySelectorAll('.conversation-card')].find(c=>c.textContent.includes('260000000106')).click()");
  await b.wait("!document.getElementById('reply').hidden && document.getElementById('reply-send').disabled && document.getElementById('reply-note').textContent.includes('24 hours')", 'window closed');
  checks.push('reply box explains the WhatsApp 24-hour rule');
  await b.evaluate("[...document.querySelectorAll('.conversation-card')].find(c=>c.textContent.includes('260000000101')).click()");
  await b.wait("!document.getElementById('reply').hidden && !document.getElementById('reply-send').disabled && document.querySelectorAll('.message').length>0", 'reply open');
  assert.equal(await b.evaluate("document.getElementById('mode-badge').textContent"), 'Staff replies on');
  await value('reply-text', 'Synthetic staff reply from the browser'); await b.evaluate("document.getElementById('reply').requestSubmit()");
  await b.wait("document.getElementById('reply-note').textContent==='Sent.' && [...document.querySelectorAll('.message.staff')].some(m=>m.textContent.includes('Staff · Synthetic admin') && m.textContent.includes('Synthetic staff reply from the browser'))", 'reply sent');
  assert.equal(await b.evaluate("document.getElementById('reply-text').value"), '');
  checks.push('admin sends a staff reply; it appears in the history labelled with their name');
  const shot = await b.send('Page.captureScreenshot', { format: 'png' }); await writeFile('.local/firebase-dashboard.png', Buffer.from(shot.data, 'base64'));
  await b.navigate('/staff.html'); await b.wait("!document.getElementById('admin').hidden", 'staff');
  const staffShot = await b.send('Page.captureScreenshot', { format: 'png' }); await writeFile('.local/staff-page.png', Buffer.from(staffShot.data, 'base64'));
  assert.deepEqual(b.errors, []);
  assert(!b.external.some(o => o.includes('gstatic') || o.includes('googleapis')));
  checks.push('no page exceptions; no real Firebase or Google requests');
  process.stdout.write(JSON.stringify({ result: { passed: checks.length, checks, pageErrors: b.errors, blockedExternalOrigins: [...new Set(b.external)] } }) + '\n');
} catch (e) { process.stdout.write(JSON.stringify({ failure: e.stack, pageErrors: b.errors }) + '\n'); process.exitCode = 1; }
finally { clearTimeout(deadline); await b.close(); }
