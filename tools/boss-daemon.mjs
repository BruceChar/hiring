// Raw-CDP daemon for BOSS直聘 automation — NO playwright/puppeteer, NO standalone Chrome.
// - Connects to the USER's everyday Chrome on --remote-debugging-port=9222 (normal
//   fingerprint + BOSS login state; standalone profiles get flagged as "环境异常" code 37).
// - ONLY uses Runtime.evaluate / Page.navigate / Page.captureScreenshot / Target.createTarget —
//   never enables Runtime/Console/Log domains.
//   BOSS 探针：页内 console.log 一个带 getter 的对象，只有 CDP Runtime 域被 enable 时
//   console 参数才会被序列化（getter 被触发）→ 判定调试器附着 → 页面清成 about:blank。
//   只发单条命令、不 enable 任何域 → getter 不触发 → 不命中。
// - Stays alive; executes commands dropped into data/raw/commands/*.json,
//   writes data/raw/results/<id>.json（工作目录全部收敛到 data/ 下，随用户数据迁移）
// - Exits when data/raw/commands/STOP exists. Writes ./data/raw/daemon.pid while alive.
import fs from 'node:fs';
import path from 'node:path';
import cp from 'node:child_process';

import { fileURLToPath } from 'node:url';
const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));  // 项目根（自适应）
const CMDS = path.join(ROOT, 'data', 'raw', 'commands');
const RESULTS = path.join(ROOT, 'data', 'raw', 'results');
const LOGF = path.join(ROOT, 'data', 'logs', 'daemon.log');
const PIDF = path.join(ROOT, 'data', 'raw', 'daemon.pid');
const PORT = Number(process.env.CDP_PORT || 9222);   // 用户日常 Chrome 的调试口

for (const d of [CMDS, RESULTS, path.dirname(LOGF), path.dirname(PIDF)]) fs.mkdirSync(d, { recursive: true });

const log = (...a) => {
  const line = `[${new Date().toISOString()}] ${a.join(' ')}`;
  console.log(line);
  fs.appendFileSync(LOGF, line + '\n');
};

async function waitForDebugger(timeoutMs = 30000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    try {
      const r = await fetch(`http://127.0.0.1:${PORT}/json/version`);
      if (r.ok) return await r.json();
    } catch (e) { /* 未就绪，重试 */ }
    await new Promise((r) => setTimeout(r, 400));
  }
  throw new Error(`用户 Chrome 调试口 ${PORT} 未就绪（需以 --remote-debugging-port=${PORT} 启动 Chrome）`);
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
      const msg = JSON.parse(ev.data);
      if (msg.id && pending.has(msg.id)) {
        const { res, rej } = pending.get(msg.id);
        pending.delete(msg.id);
        if (msg.error) rej(new Error(JSON.stringify(msg.error)));
        else res(msg.result);
      }
    });
  });
}

async function json(pathname) {
  return await (await fetch(`http://127.0.0.1:${PORT}${pathname}`)).json();
}

async function browserWs() {
  const v = await json('/json/version');
  return v.webSocketDebuggerUrl;
}

// 选页：优先 zhipin tab → 其次非空白页 → 第一页（避免错页）
async function pageTarget(filter) {
  const list = await json('/json/list');
  const pages = list.filter((t) => t.type === 'page');
  if (!pages.length) throw new Error('no page target');
  if (filter) return pages.find((t) => t.url.includes(filter)) || pages[0];
  const zp = pages.filter((t) => t.url.includes('zhipin.com'));
  if (zp.length) return zp[zp.length - 1];
  const real = pages.filter((t) => t.url !== 'about:blank');
  return real.length ? real[real.length - 1] : pages[0];
}

async function listPages() {
  return (await json('/json/list')).filter((t) => t.type === 'page').map((t) => t.url);
}

// ---- 独立 tab 管理（批量并行采集用）：创建/关闭，互不干扰、不留垃圾 tab ----
async function createTab(url) {
  const b = await connect(await browserWs());
  let targetId;
  try {
    const r = await b.send('Target.createTarget', { url });
    targetId = r.targetId;
  } finally {
    b.close();
  }
  for (let i = 0; i < 30; i++) {
    try {
      const pg = await connect(`ws://127.0.0.1:${PORT}/devtools/page/${targetId}`);
      return { tab: pg, id: targetId };
    } catch (e) {
      await new Promise((r) => setTimeout(r, 300));
    }
  }
  throw new Error('tab attach timeout: ' + targetId);
}

async function closeTab(id) {
  try {
    const b = await connect(await browserWs());
    try { await b.send('Target.closeTarget', { targetId: id }); } finally { b.close(); }
  } catch (e) { /* 关闭失败忽略（Chrome 已清理） */ }
}

// 列表页提取（collectNavs 用）：返回 {list, risk}，risk=页面出现风控特征
const EXTRACT_NAV = `(()=>{
  const cards=[...document.querySelectorAll('.job-card-wrap')];
  const txt=(el,s)=>{const e=el.querySelector(s);return e?e.innerText.trim().replace(/\\n+/g,' '):''};
  const list=cards.map((el)=>{
    const a=el.querySelector('a.job-name,a[href*="job_detail"]');
    const href=a?a.getAttribute('href')||'':'';
    const tags=[...el.querySelectorAll('.tag-list li')].map(t=>t.innerText.trim()).filter(Boolean);
    const exp=tags.find(t=>/年$|经验/.test(t))||'';
    const degree=tags.find(t=>/本科|硕士|博士|大专|中专|高中|学历/.test(t))||'';
    const skills=tags.filter(t=>t!==exp&&t!==degree);
    const actm=(el.innerText.match(/(刚刚活跃|今日活跃|[0-9]+日内活跃|本周活跃|本月活跃|[0-9]+月内活跃|更早)/)||[])[0]||'';
    return {
      name: a?a.innerText.trim():'',
      salary: txt(el,'.job-salary'), company: txt(el,'.boss-name'),
      area: txt(el,'.company-location'),
      exp: exp, degree: degree,
      tags: skills.join('/'),
      boss: '', activity: actm, href: href,
      id: (href.match(/job_detail\\/([^.?]+)/)||[])[1]||''
    };
  });
  const body=document.body?document.body.innerText:'';
  const risk=/环境异常|安全验证|verify|security-check|验证码/i.test(location.href+' '+body);
  return { list: list, risk: risk };
})()`;

// 详情页提取（collectDetails 用）：明文薪资 + JD + 风控特征
const EXTRACT_DETAIL = `(()=>{
  const body=document.body?document.body.innerText.replace(/\\n+/g,' '):'';
  const m=body.match(/(\\d+(\\.\\d+)?-\\d+(\\.\\d+)?K[^\\s]*)|(\\d+(\\.\\d+)?-\\d+(\\.\\d+)?元\\/天)/);
  // 优先用 .boss-active-time 精确抓 HR 活跃度（列表页右侧 panel 和详情页都有这个 class）
  const actEl=document.querySelector('.boss-active-time');
  const am=actEl?actEl.innerText.trim():(body.match(/(刚刚活跃|今日活跃|[0-9]+日内活跃|本周活跃|本月活跃|[0-9]+月内活跃|更早)/)||[])[0]||'';
  const sec=document.querySelector('.job-sec-text');
  const jd=(sec?sec.innerText:body).slice(0,3000);
  const risk=/环境异常|安全验证|verify|security-check|验证码/i.test(location.href+' '+body);
  return { salary: m?m[0]:'', activity: am, jd: jd, risk: risk };
})()`;

async function evalOn(target, expression) {
  const p = await connect(target.webSocketDebuggerUrl);
  try {
    const r = await p.send('Runtime.evaluate', {
      expression, returnByValue: true, awaitPromise: true, userGesture: true,
    });
    if (r.exceptionDetails) throw new Error('JS EXCEPTION: ' + JSON.stringify(r.exceptionDetails).slice(0, 300));
    return r.result.value;
  } finally {
    p.close();
  }
}

async function run(action, args) {
  const target = await pageTarget(args.filter);
  const p = await connect(target.webSocketDebuggerUrl);
  try {
    switch (action) {
      case 'state': {
        const { result } = await p.send('Runtime.evaluate', {
          expression: '({url: location.href, title: document.title})', returnByValue: true,
        });
        return { url: result.value.url, title: result.value.title, pages: await listPages() };
      }
      case 'goto': {
        await p.send('Page.navigate', { url: args.url });
        await new Promise((r) => setTimeout(r, args.wait ?? 3000));
        const { result } = await p.send('Runtime.evaluate', {
          expression: '({url: location.href, title: document.title})', returnByValue: true,
        });
        return result.value;
      }
      case 'eval':
        return await evalOn(target, args.js);
      case 'evalFile':
        return await evalOn(target, fs.readFileSync(args.file.startsWith('/') ? args.file : path.join(ROOT, args.file), 'utf8'));
      case 'shot': {
        const { data } = await p.send('Page.captureScreenshot', {
          format: 'png', captureBeyondViewport: !!args.fullPage,
        });
        const out = path.join(ROOT, args.path);
        fs.mkdirSync(path.dirname(out), { recursive: true });
        fs.writeFileSync(out, Buffer.from(data, 'base64'));
        return { saved: args.path, url: target.url };
      }
      case 'click': {
        // 定位后 el.click()（投递阶段可再升级为 Input.dispatchMouseEvent 真实鼠标事件）
        const expr = args.text
          ? `(()=>{const els=[...document.querySelectorAll('button,a,div,span')].filter(e=>e.textContent.trim()===${JSON.stringify(args.text)});const el=els[els.length-1]||null;if(!el)return null;el.scrollIntoView({block:'center'});el.click();return true})()`
          : `(()=>{const el=document.querySelector(${JSON.stringify(args.selector)});if(!el)return null;el.scrollIntoView({block:'center'});el.click();return true})()`;
        await p.send('Runtime.evaluate', { expression: expr, returnByValue: true, userGesture: true });
        await new Promise((r) => setTimeout(r, args.wait ?? 1500));
        return { ok: true };
      }
      case 'loginCheck': {
        // 登录态探测：头像/用户区 + 非校验页才算已登录（verify/login/passport 页一律视为未登录）
        const { result } = await p.send('Runtime.evaluate', {
          expression: `(()=>{
            const u=location.href;
            const verify=/passport|verify|login|register|code=3[0-9]/i.test(u);
            const t=document.body?document.body.innerText:'';
            const hasAvatar=!!document.querySelector('.user-card,.user-info,[class*="avatar"],[class*="user-card"],[class*="user-nav"]');
            const logged=!verify&&(hasAvatar||/退出|我的简历/.test(t));
            return {logged:!!logged, url:u, verify:!!verify, hasAvatar:!!hasAvatar};
          })()`,
          returnByValue: true,
        });
        return result.value;
      }
      case 'collectNav': {
        // 页面导航式采集：逐 关键词×城市 导航列表页 → DOM 提取（不用内部 XHR，防「环境异常」）
        // 节奏：导航 12-16s / 步间 4-6s（SKILL 反风控纪律）
        const navWait = args.navWait ?? 13000;
        const stepWait = args.stepWait ?? 4000;
        // 采集筛选：salary（如 "30-50" → salary=30_50，单位 K，URL 参数实测生效）；
        // recruitType：'校招' → 导航后页面内点击「求职类型→校招」（社招/不配置 = BOSS 默认列表即社招，不处理）
        const salary = args.salary ? `&salary=${String(args.salary).replace(/[^\d_]/g, '_').replace(/_+/g, '_').replace(/^_|_$/g, '')}` : '';
        const out = [];
        const base = 'https://www.zhipin.com/web/geek/jobs';
        for (const [cityName, city] of Object.entries(args.cities || {})) {
          for (const kw of args.keywords || []) {
            const url = `${base}?query=${encodeURIComponent(kw)}&city=${city}${salary}`;
            try {
              await p.send('Page.navigate', { url });
              await new Promise((r) => setTimeout(r, navWait));
              if (args.recruitType === '校招') {
                try {
                  // 点开「求职类型」下拉 → 选「校招」；失败不阻断采集（记日志）
                  const r1 = await p.send('Runtime.evaluate', {
                    expression: `(()=>{const sels=[...document.querySelectorAll('.current-select')];const t=sels.find(e=>/求职类型/.test(e.innerText||''));if(!t)return false;t.click();return true})()`,
                    returnByValue: true,
                  });
                  if (r1.result && r1.result.value) {
                    await new Promise((r) => setTimeout(r, 1500));
                    const r2 = await p.send('Runtime.evaluate', {
                      expression: `(()=>{const o=[...document.querySelectorAll('li,div')].find(e=>e.innerText&&e.innerText.trim()==='校招');if(!o)return false;o.click();return true})()`,
                      returnByValue: true,
                    });
                    if (!(r2.result && r2.result.value)) log('collectNav 校招选项点击失败（页面结构变化），继续默认列表');
                    else await new Promise((r) => setTimeout(r, 1500));
                  } else {
                    log('collectNav 求职类型下拉未找到（默认社招列表），继续');
                  }
                } catch (e) { log('collectNav 校招筛选跳过:', String(e && e.message ? e.message : e)); }
              }
              const r = await p.send('Runtime.evaluate', {
                expression: `(()=>{
                  const cards=[...document.querySelectorAll('.job-card-wrap')];
                  const txt=(el,s)=>{const e=el.querySelector(s);return e?e.innerText.trim().replace(/\\n+/g,' '):''};
                  return cards.map((el)=>{
                    const a=el.querySelector('a.job-name,a[href*="job_detail"]');
                    const href=a?a.getAttribute('href')||'':'';
                    const tags=[...el.querySelectorAll('.tag-list li')].map(t=>t.innerText.trim()).filter(Boolean);
                    const exp=tags.find(t=>/年$|经验/.test(t))||'';
                    const degree=tags.find(t=>/本科|硕士|博士|大专|中专|高中|学历/.test(t))||'';
                    const skills=tags.filter(t=>t!==exp&&t!==degree);
                    const actm=(el.innerText.match(/(刚刚活跃|今日活跃|[0-9]+日内活跃|本周活跃|本月活跃|[0-9]+月内活跃|更早)/)||[])[0]||'';
                    return {
                      name: a?a.innerText.trim():'',
                      salary: txt(el,'.job-salary'), company: txt(el,'.boss-name'),
                      area: txt(el,'.company-location'),
                      exp: exp, degree: degree,
                      tags: skills.join('/'),
                      boss: '', activity: actm, href: href,
                      id: (href.match(/job_detail\\/([^.?]+)/)||[])[1]||''
                    };
                  });
                })()`,
                returnByValue: true,
              });
              const list = r.result.value || [];
              for (const j of list) { j.q = kw; j.cityName = cityName; out.push(j); }
              log('collectNav', kw, cityName, '->', list.length, '条');
            } catch (e) {
              log('collectNav ERR', kw, cityName, String(e && e.message ? e.message : e));
            }
            await new Promise((r) => setTimeout(r, stepWait));
          }
        }
        const seen = new Map();
        for (const j of out) if (j.id && !seen.has(j.id)) seen.set(j.id, j);
        return JSON.stringify({ total: out.length, unique: seen.size, jobs: [...seen.values()] });
      }
      case 'collectDetail': {   // 单条岗位详情页：明文薪资 + JD（采集阶段2回填用）
        const href = args.href || '';
        if (!href) return JSON.stringify({ ok: false, error: 'no href' });
        const full = href.startsWith('http') ? href : 'https://www.zhipin.com' + href;
        try {
          await p.send('Page.navigate', { url: full });
          await new Promise((r) => setTimeout(r, args.wait || 13000));
          const r = await p.send('Runtime.evaluate', {
            expression: `(()=>{
              const body=document.body?document.body.innerText.replace(/\\n+/g,' '):'';
              const m=body.match(/(\\d+(\\.\\d+)?-\\d+(\\.\\d+)?K[^\\s]*)|(\\d+(\\.\\d+)?-\\d+(\\.\\d+)?元\\/天)/);
              const am=(body.match(/(刚刚活跃|今日活跃|[0-9]+日内活跃|本周活跃|本月活跃|[0-9]+月内活跃|更早)/)||[])[0]||'';
              const sec=document.querySelector('.job-sec-text');
              const jd=(sec?sec.innerText:body).slice(0,3000);
              return { salary: m?m[0]:'', activity: am, jd: jd };
            })()`,
            returnByValue: true,
          });
          const v = (r.result && r.result.value) || {};
          return JSON.stringify({ ok: true, id: (full.match(/job_detail\/([^.?]+)/) || [])[1] || '', salary: v.salary || '', activity: v.activity || '', jd: (v.jd || '').slice(0, 2000) });
        } catch (e) {
          log('collectDetail ERR', String(e && e.message ? e.message : e));
          return JSON.stringify({ ok: false, error: String(e && e.message ? e.message : e) });
        }
      }
      case 'collectNavs': {
        // 批量并行列表采集：组合（关键词×城市）分片到多个 tab 并发；动态节流快进快退；风控信号立即降速/停
        // 默认快参数起手（8s/3s），连续正常渐进加快（最低 6s/2.5s），遇异常/风控立即退回保守（13s/4s）
        const concurrency = Math.max(1, Math.min(parseInt(args.concurrency) || 3, 4));
        let navWait = args.navWait ?? 8000;
        let stepWait = args.stepWait ?? 3000;
        const safeNav = args.safeNav ?? 13000;
        const safeStep = args.safeStep ?? 4000;
        const salary = args.salary ? `&salary=${String(args.salary).replace(/[^\d_]/g, '_').replace(/_+/g, '_').replace(/^_|_$/g, '')}` : '';
        const combos = [];
        for (const [cityName, city] of Object.entries(args.cities || {})) {
          for (const kw of args.keywords || []) combos.push({ kw, cityName, city });
        }
        if (!combos.length) return JSON.stringify({ total: 0, unique: 0, risk: false, jobs: [] });
        const base = 'https://www.zhipin.com/web/geek/jobs';
        const out = [];
        let risk = false;
        const worker = async (tab, slice) => {
          let nw = navWait, sw = stepWait, anomalies = 0;
          let first = true;
          for (const c of slice) {
            if (risk) break;
            const url = `${base}?query=${encodeURIComponent(c.kw)}&city=${c.city}${salary}`;
            try {
              await tab.send('Page.navigate', { url });
              // 新 tab 首轮需加载前端 JS/过安全校验，等待更久（14s+），后续组合才按动态节流
              await new Promise((r) => setTimeout(r, first ? Math.max(nw, 14000) : nw));
              first = false;
              if (args.recruitType === '校招') {
                try {
                  const r1 = await tab.send('Runtime.evaluate', {
                    expression: `(()=>{const sels=[...document.querySelectorAll('.current-select')];const t=sels.find(e=>/求职类型/.test(e.innerText||''));if(!t)return false;t.click();return true})()`,
                    returnByValue: true,
                  });
                  if (r1.result && r1.result.value) {
                    await new Promise((r) => setTimeout(r, 1500));
                    const r2 = await tab.send('Runtime.evaluate', {
                      expression: `(()=>{const o=[...document.querySelectorAll('li,div')].find(e=>e.innerText&&e.innerText.trim()==='校招');if(!o)return false;o.click();return true})()`,
                      returnByValue: true,
                    });
                    if (!(r2.result && r2.result.value)) log('collectNavs 校招选项点击失败（页面结构变化），继续默认列表');
                    else await new Promise((r) => setTimeout(r, 1500));
                  } else {
                    log('collectNavs 求职类型下拉未找到（默认社招列表），继续');
                  }
                } catch (e) { log('collectNavs 校招筛选跳过:', String(e && e.message ? e.message : e)); }
              }
              const r = await tab.send('Runtime.evaluate', { expression: EXTRACT_NAV, returnByValue: true });
              const v = (r.result && r.result.value) || {};
              const list = v.list || [];
              if (list.length > 0) {
                anomalies = 0;
                if (nw > 6000) nw -= 1000;       // 连续正常 → 渐进加快（列表最低 6s）
                if (sw > 2500) sw -= 500;
              } else if (v.risk) {
                anomalies += 1;                  // 空列表 + 风控特征 → 立即退回保守
                nw = safeNav; sw = safeStep;
                if (anomalies >= 2) { risk = true; break; }
              } else {
                anomalies = 0;                   // 空列表但无风控特征（关键词无结果）→ 不视为异常
              }
              for (const j of list) { j.q = c.kw; j.cityName = c.cityName; out.push(j); }
              log('collectNavs', c.kw, c.cityName, '->', list.length, '条 (nw=' + nw + ')');
            } catch (e) {
              log('collectNavs ERR', c.kw, c.cityName, String(e && e.message ? e.message : e));
              anomalies += 1;
              nw = safeNav; sw = safeStep;
            }
            await new Promise((r) => setTimeout(r, sw));
          }
        };
        const n = Math.min(concurrency, combos.length);
        const tabs = [];
        for (let i = 0; i < n; i++) {
          try { tabs.push(await createTab(base)); }
          catch (e) { log('collectNavs createTab 失败，降级为', tabs.length, '个 tab:', String(e && e.message ? e.message : e)); break; }
        }
        if (!tabs.length) throw new Error('collectNavs 全部 tab 创建失败');
        // 分片按实际 tab 数重算（取模轮转：组合只属一个分片 = 不重；全组合覆盖 = 不漏）
        const m = tabs.length;
        const slices = Array.from({ length: m }, (_, i) => combos.filter((_, idx) => idx % m === i));
        try {
          await Promise.all(tabs.map((t, i) => worker(t.tab, slices[i])));
        } finally {
          for (const t of tabs) await closeTab(t.id);
        }
        const seen = new Map();
        for (const j of out) if (j.id && !seen.has(j.id)) seen.set(j.id, j);
        if (risk) log('collectNavs 风控信号，已降速停止（risk=true）');
        return JSON.stringify({ total: out.length, unique: seen.size, risk, jobs: [...seen.values()] });
      }
      case 'collectDetails': {
        // 批量并行详情回填：岗位分片到多个 tab 并发；风控信号全局停；成功渐进加快、失败退回保守
        const jobs = args.jobs || [];
        if (!jobs.length) return JSON.stringify({ ok: true, items: [], risk: false });
        const concurrency = Math.max(1, Math.min(parseInt(args.concurrency) || 4, 5));
        let wait = args.wait ?? 9000;
        const safeWait = args.safeWait ?? 13000;
        const items = [];
        let risk = false;
        const worker = async (tab, slice) => {
          let w = wait;
          let first = true;
          for (const j of slice) {
            if (risk) break;
            const full = j.href.startsWith('http') ? j.href : 'https://www.zhipin.com' + j.href;
            try {
              await tab.send('Page.navigate', { url: full });
              // 新 tab 首轮加载更慢（详情页首轮 14s+），后续按动态节流
              await new Promise((r) => setTimeout(r, first ? Math.max(w, 14000) : w));
              first = false;
              const r = await tab.send('Runtime.evaluate', { expression: EXTRACT_DETAIL, returnByValue: true });
              const v = (r.result && r.result.value) || {};
              if (v.risk) { risk = true; break; }
              items.push({ id: j.id, salary: v.salary || '', activity: v.activity || '', jd: (v.jd || '').slice(0, 2000) });
              if (w > 6000) w -= 1000;           // 连续成功 → 详情等待渐进加快（最低 6s）
              log('collectDetails', j.id, '->', v.salary || '(无薪资)', 'jd', (v.jd || '').length, '字 (w=' + w + ')');
            } catch (e) {
              log('collectDetails ERR', j.id, String(e && e.message ? e.message : e));
              items.push({ id: j.id, salary: '', activity: '', jd: '', error: String(e && e.message ? e.message : e).slice(0, 120) });
              w = safeWait;
            }
            await new Promise((r) => setTimeout(r, 1500));
          }
        };
        const n = Math.min(concurrency, jobs.length);
        const tabs = [];
        for (let i = 0; i < n; i++) {
          try { tabs.push(await createTab('https://www.zhipin.com/web/geek/jobs')); }
          catch (e) { log('collectDetails createTab 失败，降级为', tabs.length, '个 tab:', String(e && e.message ? e.message : e)); break; }
        }
        if (!tabs.length) throw new Error('collectDetails 全部 tab 创建失败');
        const m = tabs.length;
        const slices = Array.from({ length: m }, (_, i) => jobs.filter((_, idx) => idx % m === i));
        try {
          await Promise.all(tabs.map((t, i) => worker(t.tab, slices[i])));
        } finally {
          for (const t of tabs) await closeTab(t.id);
        }
        if (risk) log('collectDetails 风控信号，已停止（risk=true）');
        return JSON.stringify({ ok: true, items, risk });
      }
      default:
        throw new Error('unknown action: ' + action);
    }
  } finally {
    p.close();
  }
}

// ---------------- 主循环 ----------------
async function ensureChrome() {
  // 模式：**独立调试 Chrome**（独立 profile + 独立窗口），与用户日常 Chrome 互不干扰。
  // - profile 放项目内 data/raw/chrome-boss-profile（不在 ~/Library，避开 TCC 权限限制，且可随 data/ 迁移）
  // - 复用已有 9222 实例（排除 headless；headless 无窗口/无登录态）
  try {
    const v = await waitForDebugger(3000);
    if (!/headless/i.test(v.Browser || '')) return v;
    log('9222 is headless instance, ignoring:', v.Browser);
  } catch (e) { /* 未就绪，拉起独立 Chrome */ }
  const candidates = [
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    process.env.CHROME_BIN || '',
  ].filter(Boolean);
  if (!candidates.length) throw new Error(`Chrome 调试口 ${PORT} 未就绪，且找不到 Chrome`);
  const prof = path.join(ROOT, 'data', 'raw', 'chrome-boss-profile');
  fs.mkdirSync(prof, { recursive: true });
  log('launching dedicated Chrome (debug port', PORT + ', profile', prof + ')');
  cp.spawn(candidates[0], [
    `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${prof}`,
    '--no-first-run', '--no-default-browser-check',
    'https://www.zhipin.com/web/geek/jobs',
  ], { detached: true, stdio: 'ignore' }).unref();
  const v = await waitForDebugger(30000);
  log('dedicated Chrome connected |', v.Browser || v['User-Agent'] || '');
  return v;
}

async function main() {
  // 单次命令模式（server subprocess 调用）：直接用同一套 CDP 执行，不写命令队列、不建根目录
  // 支持：loginCheck（登录态）/ collectNav（列表采集）/ collectDetail（详情回填）/ state / goto / eval / shot
  const solo = process.argv[2];
  if (solo && ['loginCheck', 'collectNav', 'collectDetail', 'collectNavs', 'collectDetails', 'state', 'goto', 'eval', 'shot'].includes(solo)) {
    try {
      const args = process.argv[3] ? JSON.parse(process.argv[3]) : {};
      const v = await ensureChrome();
      const out = await run(solo, args);
      console.log(typeof out === 'string' ? out : JSON.stringify(out, null, 2));
    } catch (e) {
      console.log(JSON.stringify({ ok: false, error: String(e && e.message ? e.message : e).slice(0, 200) }));
    }
    process.exit(0);
  }
  try { fs.unlinkSync(path.join(CMDS, 'STOP')); } catch (e) {}

  const v = await ensureChrome();
  log('connected to Chrome on port', PORT, '|', v.Browser || v['User-Agent'] || '');

  // 启动即确保有 zhipin 标签并**激活到前台**（用户直接看到登录页）
  try {
    let target;
    try { target = await pageTarget('zhipin.com'); }
    catch (e) { target = null; }
    const b = await connect(await browserWs());
    if (!target) {
      const r = await b.send('Target.createTarget', { url: 'https://www.zhipin.com/web/geek/jobs' });
      log('opened zhipin tab, target=', r.targetId);
      await new Promise((r2) => setTimeout(r2, 2500));
      target = await pageTarget('zhipin.com');
    }
    try { await b.send('Target.activateTarget', { targetId: target.id }); } catch (e) { /* 激活失败不影响 */ }
    b.close();
    // 独立 Chrome 是新实例，启动即在前台；不要用 `open -a "Google Chrome"`（会激活用户日常 Chrome，干扰用户）
    const t = await pageTarget('zhipin.com');
    const st = await evalOn(t, 'location.href');
    log('zhipin page ready (foreground), url=', st);
    try {
      const lg = await evalOn(t, `(()=>{const t=document.body?document.body.innerText:'';return {logged: !t.includes('登录/注册')||t.includes('退出'), hasLoginBtn: t.includes('登录/注册')}})()`);
      log('login state:', JSON.stringify(lg));
    } catch (e) { /* 页面未完全加载 */ }
  } catch (e) {
    log('initial navigation failed (user can navigate manually):', String(e && e.message ? e.message : e));
  }

  try { fs.writeFileSync(PIDF, String(process.pid)); } catch (e) { log('pid file write failed', String(e)); }
  log('daemon ready, watching', CMDS);

  let stopping = false;
  process.on('SIGINT', () => (stopping = true));
  process.on('SIGTERM', () => (stopping = true));

  while (!stopping) {
    if (fs.existsSync(path.join(CMDS, 'STOP'))) {
      log('STOP file found, shutting down');
      break;
    }
    const files = fs.readdirSync(CMDS).filter((f) => f.endsWith('.json')).sort();
    for (const f of files) {
      const full = path.join(CMDS, f);
      let payload;
      try {
        payload = JSON.parse(fs.readFileSync(full, 'utf8'));
      } catch (e) {
        fs.unlinkSync(full);
        continue;
      }
      const id = payload.id || path.basename(f, '.json');
      log('CMD', id, payload.action, JSON.stringify(payload.args ?? {}).slice(0, 120));
      let out;
      try {
        const result = await run(payload.action, payload.args ?? {});
        out = { id, ok: true, result };
      } catch (e) {
        out = { id, ok: false, error: String(e && e.message ? e.message : e) };
        log('ERR', id, out.error);
      }
      fs.writeFileSync(path.join(RESULTS, id + '.json'), JSON.stringify(out, null, 2));
      fs.unlinkSync(full);
      if (payload.action === 'shutdown') {
        stopping = true;
        break;
      }
    }
    await new Promise((r) => setTimeout(r, 400));
  }

  try { fs.unlinkSync(PIDF); } catch (e) {}
  try { fs.unlinkSync(path.join(CMDS, 'STOP')); } catch (e) {}
  log('daemon exited');
  process.exit(0);
}

main().catch((e) => {
  log('FATAL', String(e && e.message ? e.message : e));
  process.exit(1);
});
