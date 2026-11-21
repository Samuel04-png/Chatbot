// Shared headless-Chrome harness: CDP over pipes, every request intercepted; same-origin requests are
// bridged over stdin/stdout to a Flask test client; selected CDN scripts are replaced by offline fakes.
import { spawn } from 'node:child_process';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import readline from 'node:readline';
export const ORIGIN = 'http://127.0.0.1:5051';
export async function startBrowser(fakes) {
  const profile = await mkdtemp(path.join(tmpdir(), 'rudo-browser-'));
  const chrome = process.env.RUDO_TEST_CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
  const proc = spawn(chrome, ['--headless=new', '--remote-debugging-pipe', '--no-first-run', '--disable-background-networking', '--disable-component-update', '--disable-sync', '--disable-default-apps', `--user-data-dir=${profile}`], { stdio: ['ignore', 'ignore', 'ignore', 'pipe', 'pipe'] });
  let seq = 0, buffer = '', session, bridgeSeq = 0;
  const pending = new Map(), events = new Map(), bridgePending = new Map(), errors = [], external = [];
  const input = readline.createInterface({ input: process.stdin });
  input.on('line', line => { const v = JSON.parse(line), p = bridgePending.get(v.id); if (p) { bridgePending.delete(v.id); p(v); } });
  const bridge = data => new Promise(resolve => { const id = ++bridgeSeq; bridgePending.set(id, resolve); process.stdout.write(JSON.stringify({ id, ...data }) + '\n'); });
  const send = (method, params = {}, sid = session) => new Promise((resolve, reject) => { const id = ++seq; pending.set(id, { resolve, reject }); proc.stdio[3].write(JSON.stringify({ id, method, params, ...(sid ? { sessionId: sid } : {}) }) + '\0'); });
  proc.stdio[4].on('data', data => { buffer += data; let i; while ((i = buffer.indexOf('\0')) >= 0) { const m = JSON.parse(buffer.slice(0, i)); buffer = buffer.slice(i + 1); if (m.id) { const p = pending.get(m.id); pending.delete(m.id); if (p) m.error ? p.reject(new Error(m.error.message)) : p.resolve(m.result); } else for (const fn of events.get(m.method) || []) Promise.resolve(fn(m.params)).catch(e => errors.push(String(e))); } });
  const on = (name, fn) => events.set(name, [...(events.get(name) || []), fn]);
  const target = await send('Target.createTarget', { url: 'about:blank' }, null);
  session = (await send('Target.attachToTarget', { targetId: target.targetId, flatten: true }, null)).sessionId;
  await send('Page.enable'); await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  on('Runtime.exceptionThrown', e => errors.push(e.exceptionDetails.exception?.description || e.exceptionDetails.text));
  on('Fetch.requestPaused', async ({ requestId, request }) => {
    const url = new URL(request.url);
    if (fakes[request.url] !== undefined) { await send('Fetch.fulfillRequest', { requestId, responseCode: 200, responseHeaders: [{ name: 'Content-Type', value: 'text/javascript' }], body: Buffer.from(fakes[request.url]).toString('base64') }); return; }
    if (url.origin !== ORIGIN) { external.push(url.origin); await send('Fetch.failRequest', { requestId, errorReason: 'BlockedByClient' }); return; }
    const r = await bridge({ request: { url: url.pathname + url.search, method: request.method, headers: request.headers, body: request.postData || null } });
    await send('Fetch.fulfillRequest', { requestId, responseCode: r.status, responseHeaders: Object.entries(r.headers).map(([name, value]) => ({ name, value })), body: r.body });
  });
  await send('Fetch.enable', { patterns: [{ urlPattern: '*' }] });
  async function evaluate(expression) { const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true }); if (r.exceptionDetails) throw Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text); return r.result?.value; }
  async function wait(expression, label) { for (let i = 0; i < 250; i++) { try { if (await evaluate(expression)) return; } catch { } await new Promise(r => setTimeout(r, 30)); } throw Error('Browser condition timed out: ' + (label || expression)); }
  async function close() { input.close(); proc.kill('SIGTERM'); await new Promise(r => setTimeout(r, 200)); await rm(profile, { recursive: true, force: true }); }
  return { send, evaluate, wait, bridge, errors, external, close, navigate: url => send('Page.navigate', { url: ORIGIN + url }) };
}
