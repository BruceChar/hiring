import path from 'node:path';
// Send the BOSS greeting ("立即沟通") for every target, with human pacing, and record results.
import fs from 'node:fs';
import { execFileSync } from 'node:child_process';

import { fileURLToPath } from 'node:url';
const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));  // 项目根（自适应）

// 目标来源：最新的每日批次清单 data/logs/daily/batch-*.json（=用户确认过的那份名单）；
// 回退到历史快照 data/raw/final_jds.json。绝不读根目录旧路径（那些文件早已不存在）。
function loadTargets() {
  const dir = `${ROOT}/data/logs/daily`;
  if (fs.existsSync(dir)) {
    const files = fs.readdirSync(dir).filter((f) => /^batch-.*\.json$/.test(f)).sort();
    if (files.length) {
      const m = JSON.parse(fs.readFileSync(`${dir}/${files[files.length - 1]}`, 'utf8'));
      if (Array.isArray(m.batch) && m.batch.length) return m.batch;
    }
  }
  const legacy = `${ROOT}/data/raw/final_jds.json`;
  if (fs.existsSync(legacy)) return JSON.parse(fs.readFileSync(legacy, 'utf8'));
  throw new Error('找不到投递目标：请先生成 data/logs/daily/batch-*.json');
}
const targets = loadTargets();
const RECORD = `${ROOT}/data/raw/投递记录.json`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const cdp = (a) => execFileSync('node', [`${ROOT}/tools/cdp.mjs`, ...a], { cwd: ROOT, encoding: 'utf8', maxBuffer: 2e7 });
const click = (a) => execFileSync('node', [`${ROOT}/tools/click.mjs`, ...a], { cwd: ROOT, encoding: 'utf8', maxBuffer: 2e7 });

const records = fs.existsSync(RECORD) ? JSON.parse(fs.readFileSync(RECORD, 'utf8')) : [];
const seen = new Set(records.map((r) => r.id));

function save() { fs.writeFileSync(RECORD, JSON.stringify(records, null, 1)); }

for (const t of targets) {
  if (seen.has(t.id)) { console.log('SKIP(recorded) ' + t.company); continue; }
  const url = `https://www.zhipin.com/job_detail/${t.id}.html`;
  console.log(`\n=== ${t.company} | ${t.position}`);
  cdp(['eval', '--inline', `location.href='${url}'; 'go'`]);
  await sleep(13000 + Math.floor(Math.random() * 3000));

  let btn = '';
  for (let i = 0; i < 3; i++) {
    try {
      const r = JSON.parse(cdp(['eval', '--inline', `JSON.stringify({url:location.href, b:[...document.querySelectorAll('a,button')].filter(e=>/立即沟通|继续沟通/.test(e.innerText)).map(e=>e.innerText.trim())})`]));
      if (r.url.includes(t.id) && r.b.length) { btn = r.b[0]; break; }
      console.log('  waiting for page… url=' + r.url.slice(0, 60));
      await sleep(9000);
    } catch (e) { await sleep(6000); }
  }
  if (!btn) { console.log('  !! page not ready'); records.push({ ...t, greet: 'page_error', at: new Date().toISOString() }); save(); continue; }
  if (btn !== '立即沟通') {
    console.log('  already contacted (' + btn + ') -> skip');
    records.push({ ...t, greet: 'already_contacted', at: new Date().toISOString() });
    save();
    continue;
  }

  try {
    click(['--text', '立即沟通']);
  } catch (e) {
    console.log('  click failed: ' + e.message.slice(0, 120));
  }
  await sleep(4000);
  // verify: button should now read 继续沟通 and the dialog should show 已发送
  let ok = false;
  try {
    const v = JSON.parse(cdp(['eval', '--inline', `JSON.stringify({b:[...document.querySelectorAll('a,button')].map(e=>e.innerText.trim()).filter(x=>/立即沟通|继续沟通/.test(x)), sent:/已发送/.test(document.body.innerText)})`]));
    ok = v.sent || v.b.includes('继续沟通');
  } catch (e) {}
  console.log('  greet ' + (ok ? 'OK' : 'UNCERTAIN'));
  records.push({ id: t.id, company: t.company, position: t.position, city: t.city, salary: t.salary, greet: ok ? 'sent' : 'uncertain', resume: 'pending', at: new Date().toISOString() });
  save();
  await sleep(9000 + Math.floor(Math.random() * 8000));
}
console.log('\nGREET DONE. records=' + records.length);
