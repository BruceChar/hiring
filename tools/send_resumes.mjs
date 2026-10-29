import path from 'node:path';
// Send each JD-tailored resume image into its BOSS conversation.
// Gate: only companies approved in resume_review.json (verdict != "fail") are delivered.
import fs from 'node:fs';
import { execFileSync } from 'node:child_process';

import { fileURLToPath } from 'node:url';
const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));  // 项目根（自适应）
const imgs = JSON.parse(fs.readFileSync(`${ROOT}/data/resumes/img/images.json`, 'utf8'));
const RECORD = `${ROOT}/data/raw/投递记录.json`;
const reviewPath = `${ROOT}/data/raw/resume_review.json`;
const review = fs.existsSync(reviewPath) ? JSON.parse(fs.readFileSync(reviewPath, 'utf8')) : { reviews: [] };
const verdict = Object.fromEntries((review.reviews || []).map((r) => [r.company, r.verdict]));

// 目标 = 最新的每日批次清单（data/logs/daily/batch-*.json）。
// keyword：在会话列表里定位该会话用的关键字。匿名公司名（「某大型…」）在聊天列表里
// 显示的是真实主体名，匹配不上——这类目标必须先在清单里补好 match 字段再发。
function loadBatch() {
  const dir = `${ROOT}/data/logs/daily`;
  const files = fs.existsSync(dir) ? fs.readdirSync(dir).filter((f) => /^batch-.*\.json$/.test(f)).sort() : [];
  if (!files.length) throw new Error('找不到 data/logs/daily/batch-*.json');
  const m = JSON.parse(fs.readFileSync(`${dir}/${files[files.length - 1]}`, 'utf8'));
  if (!Array.isArray(m.batch) || !m.batch.length) throw new Error('批次清单为空');
  return m.batch;
}
const MAP = loadBatch().map((b) => ({
  keyword: b.match || b.company,
  company: b.company,
  review: b.review || verdict[b.company] || 'unknown',
}));

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// --- resilience: make sure a zhipin page exists before every step --------------
async function ensurePage() {
  for (let i = 0; i < 5; i++) {
    const list = await (await fetch('http://127.0.0.1:9222/json/list')).json();
    const zp = list.filter((t) => t.type === 'page' && t.url.includes('zhipin.com'));
    if (zp.length > 1) {
      for (const t of zp.slice(0, -1)) await fetch(`http://127.0.0.1:9222/json/close/${t.id}`).catch(() => {});
    }
    if (zp.length >= 1) return true;
    console.log('  (no zhipin tab, reopening)');
    await fetch('http://127.0.0.1:9222/json/new?https://www.zhipin.com/web/geek/chat', { method: 'PUT' }).catch(() => {});
    await sleep(4000);
  }
  return false;
}

const cdp = (a) => execFileSync('node', [`${ROOT}/tools/cdp.mjs`, ...a], { cwd: ROOT, encoding: 'utf8', maxBuffer: 2e7 });
const click = (a) => execFileSync('node', [`${ROOT}/tools/click.mjs`, ...a], { cwd: ROOT, encoding: 'utf8', maxBuffer: 2e7 });
const upload = (a) => execFileSync('node', [`${ROOT}/tools/upload.mjs`, ...a], { cwd: ROOT, encoding: 'utf8', maxBuffer: 2e7 });

// --- guard: exactly one zhipin tab -------------------------------------------
const list = await (await fetch('http://127.0.0.1:9222/json/list')).json();
const zp = list.filter((t) => t.type === 'page' && t.url.includes('zhipin.com'));
for (const t of zp.slice(0, -1)) {
  await fetch(`http://127.0.0.1:9222/json/close/${t.id}`).catch(() => {});
  console.log('closed extra zhipin tab:', t.url.slice(0, 60));
}

const records = fs.existsSync(RECORD) ? JSON.parse(fs.readFileSync(RECORD, 'utf8')) : [];
// 精确匹配优先：文件名形如 蔡长霖-<公司>-Agent系统工程师。
// 直接用 includes 会撞名（如「某大型互联网上市公司」是「杭州某大型互联网上市公司」的子串）。
const findImg = (company) => {
  const exact = imgs.find((i) => i.name === `蔡长霖-${company}-Agent系统工程师`);
  const fuzzy = imgs.filter((i) => i.name.includes(company));
  if (!exact && fuzzy.length > 1) {
    console.log(`  !! 公司名「${company}」匹配到多张图（${fuzzy.length}），请改用精确名: ` + fuzzy.map((i) => i.name).join(' / '));
  }
  return (exact || fuzzy[0] || {}).png;
};

for (const { keyword, company, review: v } of MAP) {
 try {
  const file = findImg(company);
  console.log(`\n=== ${company} | 复核=${v} | 关键字=${keyword} | ${file ? file.split('/').pop() : 'NO IMAGE'}`);
  if (v !== 'pass') { console.log('  跳过：独立复核未通过（只有 pass 才允许投递）'); continue; }
  const prev = records.find((r) => r.company === company);
  if (prev && prev.resume === 'image_sent') { console.log('  跳过：已发送过'); continue; }
  if (!file) continue;

  if (!(await ensurePage())) { console.log('  !! 无法恢复标签页'); continue; }
  try { cdp(['eval', '--inline', `location.href='https://www.zhipin.com/web/geek/chat'; 'go'`]); } catch (e) { console.log('  nav err, retrying'); await sleep(5000); await ensurePage(); cdp(['eval', '--inline', `location.href='https://www.zhipin.com/web/geek/chat'; 'go'`]); }
  await sleep(12000);
  try { click(['--text', '全部']); await sleep(2500); } catch (e) {}   // chat list defaults to a filtered tab

  let opened = false;
  for (let attempt = 0; attempt < 3 && !opened; attempt++) {
    try { opened = click(['--sel', '.friend-content', '--contains', keyword]).includes('CLICKED'); } catch (e) {}
    if (opened) await sleep(4000);
    else { await sleep(3000); try { click(['--text', '全部']); } catch (e) {} }
  }
  if (!opened) { console.log('  !! conversation not found'); continue; }

  const head = JSON.parse(cdp(['eval', '--inline', `JSON.stringify({h:(document.querySelector('.chat-conversation')||{innerText:''}).innerText.slice(0,40).replace(/\\n/g,' '), n:document.querySelectorAll('.chat-conversation img').length})`]));
  console.log('  open: ' + head.h);

  try { console.log('  ' + upload(['--sel', '.btn-sendimg', '--file', file]).trim().split('\n').join(' | ')); }
  catch (e) { console.log('  UPLOAD ERR ' + e.message.slice(0, 100)); }
  await sleep(6000);

  let after = head.n;
  try { after = JSON.parse(cdp(['eval', '--inline', `JSON.stringify({n:document.querySelectorAll('.chat-conversation img').length})`])).n; } catch (e) {}
  const ok = after > head.n;
  console.log(`  images ${head.n} -> ${after} : ${ok ? 'SENT' : 'UNCERTAIN'}`);

  const rec = records.find((r) => r.company === company);
  if (rec) { rec.resume = ok ? 'image_sent' : 'image_uncertain'; rec.resumeAt = new Date().toISOString(); rec.review = v || 'unknown'; }
  else records.push({ company, resume: ok ? 'image_sent' : 'image_uncertain', resumeAt: new Date().toISOString(), review: v });
  fs.writeFileSync(RECORD, JSON.stringify(records, null, 1));

  await sleep(18000 + Math.floor(Math.random() * 14000));
 } catch (e) { console.log('  !! 本家异常，继续下一家: ' + String(e.message).slice(0,90)); }
}
console.log('\nRESUME SEND DONE');
