// Real-mouse click on the zhipin page (CDP Input domain; no Runtime.enable -> not detectable).
// Usage: node tools/click.mjs --text "立即沟通"        click first visible element whose text matches
//        node tools/click.mjs --sel ".btn-startchat"  click first element matching selector
//        node tools/click.mjs --text "X" --index 2
import fs from 'node:fs';

const PORT = process.env.CDP_PORT || 9222;
const args = process.argv.slice(2);
const get = (k) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : null; };
const text = get('--text');
const sel = get('--sel');
const index = Number(get('--index') || 0);

async function json(p) { return (await fetch(`http://127.0.0.1:${PORT}${p}`)).json(); }
function connect(wsUrl) {
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
    });
  });
}

const list = await json('/json/list');
const pages = list.filter((t) => t.type === 'page' && t.url.includes('zhipin.com'));
if (!pages.length) { console.log('NO_ZHIPIN_PAGE'); process.exit(1); }
const page = pages[pages.length - 1];
const c = await connect(page.webSocketDebuggerUrl);

const expr = `(() => {
  const q = ${JSON.stringify(sel)};
  const contains = ${JSON.stringify(get('--contains') || '')};
  let els;
  if (q) els = [...document.querySelectorAll(q)];
  else if (contains) els = [...document.querySelectorAll('a,button,div,span,li,i')].filter(e => (e.innerText||'').includes(contains));
  else els = [...document.querySelectorAll('a,button,div,span,li,i')].filter(e => (e.innerText||'').trim() === ${JSON.stringify(text || '')});
  if (contains && q) els = els.filter(e => (e.innerText||'').includes(contains));
  const vis = els.filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; });
  const el = vis[${index}] || vis[0];
  if (!el) return JSON.stringify({ ok:false, total: els.length, visible: vis.length });
  el.scrollIntoView({ block:'center', inline:'center' });
  window.__zpClickEl = el;
  return JSON.stringify({ scrolled:true, total: els.length, visible: vis.length });
})()`;

const r = await c.send('Runtime.evaluate', { expression: expr, returnByValue: true });
const info = JSON.parse(r.result.value);
if (!info.scrolled) { console.log('NOT_FOUND', JSON.stringify(info)); c.close(); process.exit(2); }
await new Promise((res) => setTimeout(res, 700)); // let smooth scrolling settle
const r2 = await c.send('Runtime.evaluate', { expression: `(()=>{const el=window.__zpClickEl; if(!el) return JSON.stringify({ok:false}); const b=el.getBoundingClientRect(); return JSON.stringify({ok:true, x:Math.round(b.left+b.width/2), y:Math.round(b.top+b.height/2), w:Math.round(b.width), h:Math.round(b.height), inView: b.top>=0 && b.bottom<=innerHeight, txt:(el.innerText||el.className||'').slice(0,40)});})()`, returnByValue: true });
const info2 = JSON.parse(r2.result.value);
if (!info2.ok) { console.log('NOT_FOUND_AFTER_SCROLL'); c.close(); process.exit(2); }
Object.assign(info, info2);

await c.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: info.x, y: info.y });
await new Promise((r) => setTimeout(r, 120));
await c.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: info.x, y: info.y, button: 'left', buttons: 1, clickCount: 1 });
await new Promise((r) => setTimeout(r, 70));
await c.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: info.x, y: info.y, button: 'left', buttons: 0, clickCount: 1 });
console.log('CLICKED', JSON.stringify(info));
c.close();
