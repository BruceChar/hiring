// Render a local HTML file to PDF using Chrome (CDP printToPDF).
// Usage: node tools/print_pdf.mjs <input.html> <output.pdf> [--header-footer]
// Port: 9223 = headless 打印专用（9222 保留给用户日常 Chrome / boss-daemon 采集投递）
import fs from 'node:fs';
import path from 'node:path';

const PORT = process.env.CDP_PORT || 9223;
const [input, output] = process.argv.slice(2);
const abs = path.resolve(input);
const fileUrl = 'file://' + abs.split('/').map(encodeURIComponent).join('/').replace(/%3A/, ':');

async function json(p) {
  return (await fetch(`http://127.0.0.1:${PORT}${p}`)).json();
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
      const m = JSON.parse(ev.data);
      if (m.id && pending.has(m.id)) {
        const { res, rej } = pending.get(m.id);
        pending.delete(m.id);
        m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result);
      }
    });
  });
}

const version = await json('/json/version');
const browser = await connect(version.webSocketDebuggerUrl);
const { targetId } = await browser.send('Target.createTarget', { url: 'about:blank' });

let pageWs = null;
for (let i = 0; i < 40 && !pageWs; i++) {
  const list = await json('/json/list');
  const t = list.find((x) => x.id === targetId);
  if (t && t.webSocketDebuggerUrl) pageWs = t.webSocketDebuggerUrl;
  else await new Promise((r) => setTimeout(r, 250));
}
if (!pageWs) throw new Error('target not found');

const page = await connect(pageWs);
await page.send('Page.enable');
await page.send('Page.navigate', { url: fileUrl });

for (let i = 0; i < 60; i++) {
  await new Promise((r) => setTimeout(r, 250));
  try {
    const r = await page.send('Runtime.evaluate', { expression: 'document.readyState', returnByValue: true });
    if (r.result.value === 'complete') break;
  } catch {}
}
await new Promise((r) => setTimeout(r, 700));

const { data } = await page.send('Page.printToPDF', {
  printBackground: true,
  paperWidth: 8.27,
  paperHeight: 11.69,
  marginTop: 0.35,
  marginBottom: 0.35,
  marginLeft: 0.4,
  marginRight: 0.4,
  preferCSSPageSize: false,
});
fs.writeFileSync(output, Buffer.from(data, 'base64'));
console.log(JSON.stringify({ output, bytes: fs.statSync(output).size }));

page.close();
await browser.send('Target.closeTarget', { targetId }).catch(() => {});
browser.close();
