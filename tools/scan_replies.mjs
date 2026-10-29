import path from 'node:path';
// Scan every applied conversation and detect whether the recruiter has replied.
import fs from 'node:fs';
import { execFileSync } from 'node:child_process';

import { fileURLToPath } from 'node:url';
const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));  // 项目根（自适应）
// 以 data/applications.json 为准（已投递集合会变化，别读历史快照）
const targets = JSON.parse(fs.readFileSync(`${ROOT}/data/applications.json`, 'utf8'));
const KEY = {
  '滴滴出行': '滴滴出行', '蚂蚁集团': '蚂蚁集团', '连连支付': '连连支付', '珀莱雅': '珀莱雅',
  '腾讯': '腾讯', '昊美科技': '昊美', '深圳图灵集市科技': '图灵集市',
  '杭州纳速码科技': '纳速码', '上海未见之境': '未见之境', '京东物流': '京东物流',
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const cdp = (a) => execFileSync('node', [`${ROOT}/tools/cdp.mjs`, ...a], { cwd: ROOT, encoding: 'utf8', maxBuffer: 2e7 });
const click = (a) => execFileSync('node', [`${ROOT}/tools/click.mjs`, ...a], { cwd: ROOT, encoding: 'utf8', maxBuffer: 2e7 });

cdp(['eval', '--inline', `location.href='https://www.zhipin.com/web/geek/chat'; 'go'`]);
await sleep(12000);
try { click(['--text', '全部']); await sleep(2500); } catch (e) {}

const out = [];
for (const t of targets) {
  const k = KEY[t.company] || t.company;
  let opened = false;
  try { opened = click(['--sel', '.friend-content', '--contains', k]).includes('CLICKED'); } catch (e) {}
  await sleep(4000);
  if (!opened) { console.log('MISS ' + t.company); out.push({ company: t.company, replied: 'unknown' }); continue; }
  const d = JSON.parse(cdp(['eval', '--inline', `(() => { const F=[...document.querySelectorAll('.message-item.item-friend')].map(e=>e.innerText.replace(/\\n+/g,' ').trim()).filter(t=>t && !/竞争者PK|查看详细分析|共人投递|优秀竞争者/.test(t)); return JSON.stringify({friend:F}); })()`]));
  const F = d.friend || [];
  const text = F.join(' | ');
  const hasReply = F.length > 0;
  const askedResume = /我想要一份您的附件简历|是否同意/.test(text);
  console.log(`${t.company}: ${hasReply ? '有回复' : '暂无回复'} ${askedResume ? '[索要简历]' : ''}`);
  out.push({ company: t.company, replied: hasReply ? 'yes' : 'no', askedResume, snippet: text.slice(0, 300) });
  fs.writeFileSync(`${ROOT}/data/raw/replies.json`, JSON.stringify(out, null, 1));
  await sleep(3000 + Math.floor(Math.random() * 3000));
}
console.log('SCAN DONE');
