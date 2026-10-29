import path from 'node:path';
// Fetch JD text for every target by opening its detail page like a human.
import fs from 'node:fs';
import { execFileSync } from 'node:child_process';

import { fileURLToPath } from 'node:url';
const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));  // 项目根（自适应）
const targets = JSON.parse(fs.readFileSync(`${ROOT}/targets.json`, 'utf8'));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const cdp = (args) => execFileSync('node', [`${ROOT}/tools/cdp.mjs`, ...args], { cwd: ROOT, encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 });

const out = [];
for (const t of targets) {
  const url = `https://www.zhipin.com/job_detail/${t.id}.html`;
  console.log('\n=== ' + t.company + ' | ' + t.name);
  cdp(['eval', '--inline', `location.href='${url}'; 'go'`]);
  await sleep(13000 + Math.floor(Math.random() * 4000));
  let data = null;
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const raw = cdp(['eval', 'tools/jd2.js']);
      data = JSON.parse(raw);
      if (data.url.includes('job_detail')) break;
      console.log('  (security check, retry) url=' + data.url.slice(0, 70));
      await sleep(9000);
    } catch (e) {
      console.log('  eval error: ' + e.message.slice(0, 120));
      await sleep(5000);
    }
  }
  if (!data) { out.push({ ...t, error: 'no data' }); continue; }
  const rec = { ...t, title: data.title, salary: data.salary, companyPage: data.company, btn: data.btn, jd: data.jd };
  out.push(rec);
  console.log('  title=' + data.title.slice(0, 40) + ' salary=' + data.salary + ' btn=' + JSON.stringify(data.btn));
  fs.writeFileSync(`${ROOT}/jds.json`, JSON.stringify(out, null, 1));
  await sleep(6000 + Math.floor(Math.random() * 5000));
}
console.log('\nDONE ' + out.length);
