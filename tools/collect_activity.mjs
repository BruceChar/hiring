import path from 'node:path';
// Collect recruiter/job activity + current contact state for every applied job.
import fs from 'node:fs';
import { execFileSync } from 'node:child_process';

import { fileURLToPath } from 'node:url';
const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));  // 项目根（自适应）
const targets = JSON.parse(fs.readFileSync(`${ROOT}/final_jds.json`, 'utf8'));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const cdp = (a) => execFileSync('node', [`${ROOT}/tools/cdp.mjs`, ...a], { cwd: ROOT, encoding: 'utf8', maxBuffer: 2e7 });

const probe = `(() => {
  const txt = document.body.innerText;
  const act = (txt.match(/(刚刚活跃|今日活跃|今日回复|本周活跃|3日内活跃|三日内活跃|2周内活跃|2周内回复|半年前活跃|本月活跃|\\d+日内活跃|\\d+月内活跃)/) || [])[0] || '';
  const boss = (document.querySelector('.boss-info .name, .boss-name, .info-public .name') || {}).innerText || '';
  const bossTitle = (document.querySelector('.boss-info .gray, .boss-info-title, .info-public .gray') || {}).innerText || '';
  const btns = [...document.querySelectorAll('a,button')].map(e => e.innerText.trim()).filter(x => /立即沟通|继续沟通/.test(x));
  const online = /在线|刚刚活跃/.test(txt);
  return JSON.stringify({ url: location.href, title: document.title.split('招聘')[0].replace(/[「」_]/g,''), act, boss: boss.trim(), bossTitle: bossTitle.trim(), btns, online });
})()`;

const out = [];
for (const t of targets) {
  console.log('\n=== ' + t.company);
  cdp(['eval', '--inline', `location.href='https://www.zhipin.com/job_detail/${t.id}.html'; 'go'`]);
  await sleep(13000 + Math.floor(Math.random() * 3000));
  let d = null;
  for (let i = 0; i < 3; i++) {
    try {
      d = JSON.parse(cdp(['eval', '--inline', probe]));
      if (d.url.includes(t.id)) break;
      await sleep(8000);
    } catch (e) { await sleep(5000); }
  }
  if (!d) { console.log('  FAIL'); out.push({ ...t, activity: 'unknown' }); continue; }
  console.log(`  boss=${d.boss} ${d.bossTitle} | 活跃=${d.act || '未标注'} | btns=${d.btns.join(',')}`);
  out.push({ id: t.id, company: t.company, position: t.position, city: t.city, salary: d.salary || t.salary, activity: d.act, boss: d.boss, bossTitle: d.bossTitle, contacted: d.btns.includes('继续沟通'), jobTitlePage: d.title, collectedAt: new Date().toISOString() });
  fs.writeFileSync(`${ROOT}/activity.json`, JSON.stringify(out, null, 1));
  await sleep(6000 + Math.floor(Math.random() * 4000));
}
console.log('\nACTIVITY DONE ' + out.length);
