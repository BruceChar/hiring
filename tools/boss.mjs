// Client for the boss daemon.
// Usage: node tools/boss.mjs <action> '<json args>'
//   node tools/boss.mjs state
//   node tools/boss.mjs goto '{"url":"https://www.zhipin.com"}'
//   node tools/boss.mjs evalFile '{"file":"tools/foo.js"}'
//   node tools/boss.mjs shot '{"path":"shots/x.png"}'
import fs from 'node:fs';
import path from 'node:path';

import { fileURLToPath } from 'node:url';
const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));  // 项目根（自适应）
const CMDS = path.join(ROOT, 'commands');
const RESULTS = path.join(ROOT, 'results');
fs.mkdirSync(CMDS, { recursive: true });
fs.mkdirSync(RESULTS, { recursive: true });

const [, , action, rawArgs] = process.argv;
const args = rawArgs ? JSON.parse(rawArgs) : {};
const id = `c${Date.now()}${Math.floor(Math.random() * 1000)}`;
const timeoutMs = Number(process.env.CMD_TIMEOUT || 90000);

fs.writeFileSync(path.join(CMDS, id + '.json'), JSON.stringify({ id, action, args }, null, 2));

const deadline = Date.now() + timeoutMs;
while (Date.now() < deadline) {
  const rf = path.join(RESULTS, id + '.json');
  if (fs.existsSync(rf)) {
    const out = JSON.parse(fs.readFileSync(rf, 'utf8'));
    fs.unlinkSync(rf);
    if (!out.ok) {
      console.error('FAILED:', out.error);
      process.exit(1);
    }
    const r = out.result;
    console.log(typeof r === 'string' ? r : JSON.stringify(r, null, 2));
    process.exit(0);
  }
  await new Promise((r) => setTimeout(r, 300));
}
console.error('TIMEOUT waiting for daemon response (is the daemon running?)');
process.exit(2);
