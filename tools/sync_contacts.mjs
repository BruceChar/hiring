// Dump BOSS 消息会话列表 → data/raw/chats.json（只读；用于投递去重的"已联系"真源）
// 背景：applications.json 只记录本工作台发起的投递，用户/其他渠道主动触达的会话不在其中，
// 只按 applications.json 去重 → 会对已联系过的公司重复打招呼。
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
const ROOT = process.cwd();
const cdp = (a) => execFileSync('node', [`${ROOT}/tools/cdp.mjs`, ...a], { cwd: ROOT, encoding: 'utf8', maxBuffer: 2e7 });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

cdp(['eval', '--inline', "location.href='https://www.zhipin.com/web/geek/chat'; 'go'"]);
await sleep(12000);

const raw = JSON.parse(cdp(['eval', '--inline',
  "JSON.stringify([...document.querySelectorAll('.friend-content')].map(e=>e.innerText.replace(/\\n+/g,' ').trim()))"]));

const GREETING = '您好，我对这份工作非常感兴趣';
const items = raw.map((t) => {
  const parts = t.split(' ');
  const askedResume = /附件简历|发一份简历|求简历/.test(t);
  const outboundOnly = t.includes(GREETING);
  return { raw: t, outboundOnly, askedResume };
});
const out = { syncedAt: new Date().toISOString(), count: items.length, items };
fs.mkdirSync(`${ROOT}/data/raw`, { recursive: true });
fs.writeFileSync(`${ROOT}/data/raw/chats.json`, JSON.stringify(out, null, 1));
console.log('SYNCED', items.length, '-> data/raw/chats.json');
