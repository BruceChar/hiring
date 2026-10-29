// Raw-CDP helper for the Chrome instance started with --remote-debugging-port=9222
// Usage:
//   node tools/cdp.mjs info
//   node tools/cdp.mjs window <left> <top> <w> <h>
//   node tools/cdp.mjs nav <url>
//   node tools/cdp.mjs shot <out.png>            (viewport screenshot)
//   node tools/cdp.mjs full <out.png>            (full-page screenshot)
//   node tools/cdp.mjs eval <file.js | --inline "js">
import fs from 'node:fs';

const PORT = process.env.CDP_PORT || 9222;
const PAGE = `http://127.0.0.1:${PORT}`;

async function json(path) {
  const r = await fetch(PAGE + path);
  return r.json();
}

function connect(wsUrl) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    let id = 0;
    const pending = new Map();
    ws.addEventListener('open', () =>
      resolve({
        send(method, params = {}) {
          const msgId = ++id;
          return new Promise((res, rej) => {
            pending.set(msgId, { res, rej });
            ws.send(JSON.stringify({ id: msgId, method, params }));
          });
        },
        close: () => ws.close(),
      })
    );
    ws.addEventListener('error', (e) => reject(new Error('ws error: ' + e.message)));
    ws.addEventListener('message', (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && pending.has(msg.id)) {
        const { res, rej } = pending.get(msg.id);
        pending.delete(msg.id);
        if (msg.error) rej(new Error(JSON.stringify(msg.error)));
        else res(msg.result);
      }
    });
  });
}

async function pageTarget(filter) {
  const list = await json('/json/list');
  const pages = list.filter((t) => t.type === 'page');
  if (!pages.length) throw new Error('no page target');
  if (filter) return pages.find((t) => t.url.includes(filter)) || pages[0];
  // Never hijack non-zhipin helper tabs (e.g. local resume HTML used for printToPDF).
  const zp = pages.filter((t) => t.url.includes('zhipin.com'));
  return zp.length ? zp[zp.length - 1] : pages[0];
}

async function browserWs() {
  const v = await json('/json/version');
  return v.webSocketDebuggerUrl;
}

const [, , cmd, ...rest] = process.argv;

if (cmd === 'info') {
  const list = await json('/json/list');
  for (const t of list) if (t.type === 'page') console.log('PAGE |', t.title, '|', t.url);
  const b = await connect(await browserWs());
  const page = await pageTarget();
  const { windowId } = await b.send('Browser.getWindowForTarget', { targetId: page.id });
  const { bounds } = await b.send('Browser.getWindowBounds', { windowId });
  console.log('WINDOW', JSON.stringify(bounds));
  b.close();
} else if (cmd === 'window') {
  const [left, top, width, height] = rest.map(Number);
  const b = await connect(await browserWs());
  const page = await pageTarget();
  const { windowId } = await b.send('Browser.getWindowForTarget', { targetId: page.id });
  await b.send('Browser.setWindowBounds', {
    windowId,
    bounds: { left, top, width, height, windowState: 'normal' },
  });
  console.log('window ->', left, top, width, height);
  b.close();
} else if (cmd === 'new') {
  const b = await connect(await browserWs());
  const r = await b.send('Target.createTarget', { url: rest[0] || 'about:blank' });
  console.log('created target', r.targetId, '->', rest[0] || 'about:blank');
  b.close();
} else {
  const target = await pageTarget(process.env.PAGE_FILTER);
  const p = await connect(target.webSocketDebuggerUrl);
  // IMPORTANT: never enable the Runtime/Console/Log domains. BOSS直聘 detects an
  // attached debugger by logging an object with a getter and checking whether the
  // getter fired (CDP serializes console args only when Runtime is enabled).
  // Runtime.evaluate / Page.captureScreenshot / DOM.* all work without enables.

  if (cmd === 'nav') {
    await p.send('Page.navigate', { url: rest[0] });
    console.log('navigating to', rest[0]);
  } else if (cmd === 'shot' || cmd === 'full') {
    const out = rest[0];
    const params = { format: 'png' };
    if (cmd === 'full') params.captureBeyondViewport = true;
    const { data } = await p.send('Page.captureScreenshot', params);
    fs.writeFileSync(out, Buffer.from(data, 'base64'));
    console.log('saved', out, fs.statSync(out).size, 'bytes', '| url=', target.url);
  } else if (cmd === 'eval') {
    const js = rest[0] === '--inline' ? rest.slice(1).join(' ') : fs.readFileSync(rest[0], 'utf8');
    const r = await p.send('Runtime.evaluate', {
      expression: js,
      returnByValue: true,
      awaitPromise: true,
      userGesture: true,
    });
    if (r.exceptionDetails) {
      console.error('JS EXCEPTION:', JSON.stringify(r.exceptionDetails).slice(0, 1200));
      process.exitCode = 1;
    } else {
      const v = r.result.value;
      console.log(typeof v === 'string' ? v : JSON.stringify(v, null, 2));
    }
  } else {
    console.error('unknown command', cmd);
    process.exitCode = 2;
  }
  p.close();
}
