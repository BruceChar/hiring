// Click an element and answer the resulting native file chooser with a local file.
// Uses Page.setInterceptFileChooserDialog + DOM.setFileInputFiles (CDP).
// Usage: node tools/upload.mjs --text "图片" --file "/abs/path.png"
import path from 'node:path';

const PORT = process.env.CDP_PORT || 9222;
const args = process.argv.slice(2);
const get = (k) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : null; };
const text = get('--text');
const sel = get('--sel');
const file = path.resolve(get('--file'));

async function json(p) { return (await fetch(`http://127.0.0.1:${PORT}${p}`)).json(); }

function connect(wsUrl, onEvent) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    let id = 0; const pending = new Map();
    ws.addEventListener('open', () => resolve({
      send(method, params = {}) {
        const msgId = ++id;
        return new Promise((res, rej) => { pending.set(msgId, { res, rej }); ws.send(JSON.stringify({ id: msgId, method, params })); });
      },
      close: () => ws.close(),
    }));
    ws.addEventListener('error', (e) => reject(new Error('ws error: ' + e.message)));
    ws.addEventListener('message', (ev) => {
      const m = JSON.parse(ev.data);
      if (m.id && pending.has(m.id)) { const { res, rej } = pending.get(m.id); pending.delete(m.id); m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result); }
      else if (m.method && onEvent) onEvent(m);
    });
  });
}

const list = await json('/json/list');
const pages = list.filter((t) => t.type === 'page' && t.url.includes('zhipin.com'));
if (!pages.length) { console.log('NO_ZHIPIN_PAGE'); process.exit(1); }
const c = await connect(pages[pages.length - 1].webSocketDebuggerUrl, async (m) => {
  if (m.method === 'Page.fileChooserOpened') {
    const backendNodeId = m.params.backendNodeId;
    try {
      await c.send('DOM.setFileInputFiles', { files: [file], backendNodeId });
      console.log('FILE_SET', file, 'mode=', m.params.mode);
    } catch (e) {
      console.log('FILE_SET_ERR', e.message);
    }
  }
});

await c.send('Page.enable');
await c.send('DOM.enable');
await c.send('Page.setInterceptFileChooserDialog', { enabled: true });

const expr = `(() => {
  const q = ${sel ? JSON.stringify(sel) : 'null'};
  const els = q ? [...document.querySelectorAll(q)] : [...document.querySelectorAll('a,button,div,span,i')].filter(e => (e.innerText||'').trim() === ${JSON.stringify(text || '')});
  const vis = els.filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; });
  const el = vis[0];
  if (!el) return JSON.stringify({ ok:false });
  el.scrollIntoView({ block:'center' });
  const r = el.getBoundingClientRect();
  return JSON.stringify({ ok:true, x: Math.round(r.left+r.width/2), y: Math.round(r.top+r.height/2), txt:(el.innerText||el.className||'').slice(0,30) });
})()`;
const info = JSON.parse((await c.send('Runtime.evaluate', { expression: expr, returnByValue: true })).result.value);
if (!info.ok) { console.log('NOT_FOUND'); process.exit(2); }

await c.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: info.x, y: info.y });
await c.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: info.x, y: info.y, button: 'left', buttons: 1, clickCount: 1 });
await c.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: info.x, y: info.y, button: 'left', buttons: 0, clickCount: 1 });
console.log('CLICKED', JSON.stringify(info));
await new Promise((r) => setTimeout(r, 4000));
c.close();
