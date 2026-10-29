// 投递前配对自检：批次清单 ↔ 简历图 ↔ 会话关键字，不发任何消息。
import fs from 'node:fs';
const ROOT = process.cwd();
const dir = `${ROOT}/data/logs/daily`;
const files = fs.readdirSync(dir).filter((f) => /^batch-.*\.json$/.test(f)).sort();
const batchFile = files[files.length - 1];
const batch = JSON.parse(fs.readFileSync(`${dir}/${batchFile}`, 'utf8'));
const imgs = JSON.parse(fs.readFileSync(`${ROOT}/data/resumes/img/images.json`, 'utf8'));
const gate = JSON.parse(fs.readFileSync(`${ROOT}/data/raw/image_check.json`, 'utf8'));
const passed = new Set(gate.items.filter((i) => i.passed).map((i) => i.file));

let problems = 0;
console.log('批次清单:', batchFile, '| 目标', batch.batch.length, '家\n');
for (const b of batch.batch) {
  const exact = imgs.find((i) => i.name === `蔡长霖-${b.company}-Agent系统工程师`);
  const file = exact ? exact.png.split('/').pop() : null;
  const problemsHere = [];
  if (!file) problemsHere.push('无对应简历图');
  else if (!passed.has(file)) problemsHere.push('图片门禁未通过');
  if (b.review !== 'pass') problemsHere.push('独立复核非 pass');
  if (!exact && /^某大型|^某知名/.test(b.company || '')) problemsHere.push('匿名公司名：发送时需补 match 关键字');
  if (problemsHere.length) problems++;
  console.log(
    (problemsHere.length ? 'WARN ' : 'OK   ') +
    String(b.company).padEnd(26) + ' | ' + String(b.salary).padEnd(12) +
    ' | ' + (file || '(无图)').padEnd(46) +
    (problemsHere.length ? ' | ' + problemsHere.join('; ') : '')
  );
}
console.log('\n可直投:', batch.batch.length - problems, '/', batch.batch.length, problems ? '（其余需人工补 match/修图）' : '');
