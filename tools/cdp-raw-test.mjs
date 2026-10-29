// Decisive test: raw CDP, NO Runtime/Console/Log domain enabled.
// Polls the page for 60s and reports whether BOSS直聘 blanks it.
import fs from 'node:fs';

const PORT = process.env.CDP_PORT || 9222;
const json = async (p) => (await fetch(`http://127.0.0.1:${PORT}${p}`)).json();

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
      const m = JSON.parse(ev.data);
      if (m.id && pending.has(m.id)) {
        const { res, rej } = pending.get(m.id);
        pending.delete(m.id);
        m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result);
      }
    });
  });
}

const list = await json('/json/list');
const page = list.find((t) => t.type === 'page');
if (!page) {
  console.log('NO PAGE TARGET');
  process.exit(1);
}
const c = await connect(page.webSocketDebuggerUrl);

const expr = `JSON.stringify({u:location.href,t:document.title,n:document.body?document.body.innerText.length:0})`;
for (let i = 0; i < 30; i++) {
  await new Promise((r) => setTimeout(r, 2000));
  try {
    const r = await c.send('Runtime.evaluate', { expression: expr, returnByValue: true });
    const v = JSON.parse(r.result.value);
    console.log(`t=${(i + 1) * 2}s`, v.u.slice(0, 55), '|', v.t.slice(0, 16), '| textLen=' + v.n);
    if (v.u === 'about:blank') {
      console.log('>>> BLANKED at', (i + 1) * 2, 's');
      break;
    }
  } catch (e) {
    console.log('EVAL ERR', e.message.slice(0, 100));
  }
}
c.close();
