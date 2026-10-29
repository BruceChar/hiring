/* 求职工作台前端 —— 无框架、无依赖 */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

async function api(path, opts = {}) {
  const r = await fetch('/api' + path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!r.ok) {
    const txt = await r.text();
    let payload = null;
    try { payload = JSON.parse(txt); } catch (e) { /* 非 JSON */ }
    const err = new Error((payload && payload.message) || txt);
    err.status = r.status; err.payload = payload;
    throw err;
  }
  const t = await r.text();
  try { return JSON.parse(t); } catch { return t; }
}
let toastTimer;
function toast(msg, bad) {
  const t = $('#toast');
  t.textContent = msg;
  t.className = 'toast show' + (bad ? ' bad' : '');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.className = 'toast'), 2600);
}
/* 顶部浮层提示：保存/另存等关键操作的结果提示，自动消失、不拦截点击（不会吞掉后续按钮点击） */
function modal(msg, ok = true) {
  const old = document.getElementById('appModal');
  if (old) old.remove();
  const m = document.createElement('div');
  m.id = 'appModal';
  m.style.cssText = 'position:fixed;inset:0;display:flex;align-items:flex-start;justify-content:center;padding-top:12vh;z-index:999;pointer-events:none';
  m.innerHTML = `<div style="background:#fff;border-radius:10px;padding:14px 20px;min-width:300px;max-width:480px;box-shadow:0 12px 40px rgba(0,0,0,.18);border-left:4px solid ${ok ? '#166534' : '#8d2f22'};pointer-events:none">
    <div style="font-size:14px;font-weight:600;color:${ok ? '#166534' : '#8d2f22'};margin-bottom:4px">${ok ? '保存成功' : '未成功'}</div>
    <div style="font-size:13px;color:#374151;line-height:1.55">${msg}</div>
  </div>`;
  document.body.appendChild(m);
  setTimeout(() => m.remove(), 1800);
}
/* 全局脚本错误横幅：页面 JS 出错时顶部直接显示，便于定位「按钮无反应」类问题 */
window.addEventListener('error', (e) => {
  const msg = (e.message || '').slice(0, 120);
  const old = document.getElementById('jsErrBar');
  if (old) old.remove();
  const bar = document.createElement('div');
  bar.id = 'jsErrBar';
  bar.style.cssText = 'position:fixed;top:0;left:0;right:0;background:#8d2f22;color:#fff;font-size:12.5px;padding:8px 14px;z-index:1000;display:flex;gap:10px;align-items:center';
  bar.innerHTML = `<span style="flex:1">页面脚本错误：${msg}</span><button style="background:none;border:1px solid #fff;color:#fff;border-radius:4px;padding:2px 10px;cursor:pointer">×</button>`;
  bar.querySelector('button').onclick = () => bar.remove();
  document.body.appendChild(bar);
});
const pct = (n) => (n == null ? '-' : n + '%');
const fmtT = (ts) => (ts || '').replace('T', ' ').slice(5, 16) || '-';   // 2026-10-01T10:34:19 → 10-01 10:34
const _daysAgo = (iso) => {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  if (isNaN(t)) return null;
  return Math.round((Date.now() - t) / 86400000);
};
const actChip = (j) => {
  const a = j.activity || '';
  if (a === '刚刚活跃') return '<span class="chip ok">刚刚活跃</span>';
  if (a === '今日活跃') return '<span class="chip on">今日活跃</span>';
  if (a === '3日内活跃') return '<span class="chip on">3日内活跃</span>';
  if (a === '本周活跃') return '<span class="chip">本周活跃</span>';
  // BOSS 已移除活跃度标签文本：根据 lastSeenAt 显示采集时间
  const d = _daysAgo(j.lastSeenAt);
  if (d == null) return '<span class="chip mute">未标注</span>';
  if (d <= 1) return '<span class="chip ok">今天采集</span>';
  if (d <= 3) return `<span class="chip on">${d} 天前采集</span>`;
  if (d <= 14) return `<span class="chip">${d} 天前采集</span>`;
  return `<span class="chip bad" title="超过 14 天未刷新，岗位可能已下架">${d} 天前采集 · 可能下架</span>`;
};

/* ---------------------------------------------------------------- views -- */
const VIEWS = {};
const HOOKS = {};   // 页面钩子（必须在所有 VIEWS/HOOKS 赋值之前声明）

async function overviewHtml() {
  const [s, cfg, onb, evd] = await Promise.all([
    api('/stats'), api('/config'), api('/onboarding'),
    api('/events?limit=20').catch(() => ({ events: [] })),
  ]);
  const onbCard = onb.complete ? '' : `<div class="card" style="border-left:4px solid var(--warn)">
    <h3>开始使用前，还有 ${onb.missing.length} 项待补 <span class="tag">Agent 会据此向你提问</span></h3>
    ${onb.items.map((i) => `<div class="row" style="align-items:flex-start;gap:8px;margin-bottom:6px">
      <span class="chip ${i.done ? 'ok' : 'bad'}">${i.done ? '已就绪' : '待补'}</span>
      <span class="small" style="flex:1"><b>${esc(i.label)}</b>（<span class="mono">${esc(i.file)}</span>）
      ${i.done ? '' : '<br>' + esc(i.ask)}</span></div>`).join('')}
  </div>`;
  const max = Math.max(...s.funnel.map((f) => f.value), 1);
  // 饼图（donut）：投递后各阶段占比（不含"岗位池"这个最大数，否则后面看不见）
  const funnelStages = s.funnel.filter((f) => f.stage !== '岗位池');
  const total = funnelStages.reduce((a, f) => a + (f.value || 0), 0);
  const colors = ['#8b5cf6', '#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#ec4899', '#6366f1'];
  let acc = 0;
  const R = 70, C = 2 * Math.PI * R;
  const segs = funnelStages.map((f, i) => {
    const frac = total ? f.value / total : 0;
    const len = Math.max(0, C * frac - 2);
    const off = C * acc;
    acc += frac;
    return `<circle r="${R}" cx="100" cy="100" fill="none" stroke="${colors[i % colors.length]}" stroke-width="26"
      stroke-dasharray="${len} ${C - len}" stroke-dashoffset="${-off}" transform="rotate(-90 100 100)"/>`;
  }).join('');
  const appliedVal = funnelStages.find((f) => f.stage === '简历已发')?.value || funnelStages[0]?.value || 0;
  const legend = funnelStages.map((f, i) => `
    <div style="display:flex;align-items:center;gap:6px;font-size:12px;margin-bottom:3px">
      <span style="width:10px;height:10px;border-radius:2px;background:${colors[i % colors.length]};flex:none"></span>
      <span style="flex:1">${esc(f.stage)}</span>
      <b>${f.value}</b>
      <span class="muted" style="width:42px;text-align:right">${total ? Math.round(f.value / total * 100) : 0}%</span>
    </div>`).join('');
  const funnel = `<div style="display:flex;gap:16px;align-items:center;flex-wrap:wrap">
    <svg width="200" height="200" viewBox="0 0 200 200" style="flex:none">${segs}
      <text x="100" y="96" text-anchor="middle" font-size="22" font-weight="700" fill="#333">${appliedVal}</text>
      <text x="100" y="116" text-anchor="middle" font-size="11" fill="#999">已投递</text>
    </svg>
    <div style="flex:1;min-width:160px">${legend}</div>
  </div>`;
  const rate = Object.entries(s.rates).map(([k, v]) => {
    const warn = (k === '回复率' && v < 15) || (k === '面试转化率' && v === 0) || (k === '投递转化率' && v < 5);
    return `<div class="kpi"><div class="k">${esc(k)}</div><div class="v${warn ? ' warn' : ''}">${pct(v)}</div></div>`;
  }).join('');
  const bd = (name, obj) => {
    const rows = Object.entries(obj).map(([k, v]) => `<tr><td>${esc(k)}</td><td class="mono">${v.total}</td>
      <td class="mono">${v.replied}</td><td class="mono">${v.replyRate}%</td></tr>`).join('');
    return `<div class="card"><h3>${esc(name)} 维度效果</h3><table><thead><tr><th>维度</th><th>投递</th><th>回复</th><th>回复率</th></tr></thead><tbody>${rows || '<tr><td colspan=4 class="muted">暂无数据</td></tr>'}</tbody></table></div>`;
  };
  const fb = s.recentFeedback.length
    ? s.recentFeedback.map((f) => `<div class="timeline"><div class="t"><b>${esc(f.company || '')}</b>
        <span class="chip ${f.signal === 'positive' ? 'ok' : f.signal === 'negative' ? 'bad' : 'mute'}">${esc(f.type || '')}</span>
        <div class="small muted">${esc(fmtT(f.at))}</div><div class="small">${esc(f.content || '')}</div>
        ${f.action ? `<div class="small" style="color:var(--brand)">→ ${esc(f.action)}</div>` : ''}</div></div>`).join('')
    : '<div class="empty">暂无反馈记录</div>';
  const ins = (s.insights || []).map((i) => {
    const cls = i.level === 'good' ? 'ok' : i.level === 'warn' ? 'bad' : i.level === 'action' ? 'on' : 'mute';
    return `<div class="row" style="align-items:flex-start;gap:8px;margin-bottom:7px">
      <span class="chip ${cls}">${i.level === 'good' ? '数据支持' : i.level === 'warn' ? '风险' : i.level === 'action' ? '待办' : '信息'}</span>
      <span class="small" style="flex:1">${esc(i.text)}</span></div>`;
  }).join('');
  const evRows = (evd.events || []).length ? evd.events.map((e) => `
    <div class="t"><span class="chip ${e.status === 'ok' ? 'ok' : 'bad'}">${esc(e.actor || '')}</span>
      <b class="small">${esc(e.action || '')}</b>
      <span class="small muted"> ${esc((e.ts || '').slice(11, 19))}</span>
      <div class="small">${esc(e.detail || '')}</div></div>`).join('')
    : '<div class="empty">暂无 Agent 操作记录</div>';
  return `${onbCard}
  <div class="grid g4">${rate}</div>
  <div class="card"><h3>评估洞察 <span class="tag">由当前数据自动生成，用于决定下一批策略</span></h3>${ins || '<div class="empty">暂无</div>'}</div>
  <div class="split">
    <div>
      <div class="card"><h3>投递漏斗 <span class="tag">岗位池 → offer · 各阶段占比</span></h3>${funnel}</div>
    </div>
    <div>
      <div class="card"><h3>本轮搜岗参数</h3>
        <div class="kv">
          <div class="k">城市</div><div>${esc((s.configSummary.cities || []).join('、')) || '-'}</div>
          <div class="k">关键词</div><div>${esc((s.configSummary.keywords || []).join('、'))}</div>
          <div class="k">薪资</div><div>${esc(s.configSummary.salary?.min)}-${esc(s.configSummary.salary?.max)}${esc(s.configSummary.salary?.unit || '')}</div>
          <div class="k">招聘类型</div><div>${esc((s.configSummary.recruit_types || []).join('、')) || '不限'}</div>
          <div class="k">批次数量</div><div>${esc(s.configSummary.batch_size)}</div>
        </div>
        <div class="hr"></div>
        <a class="btn" href="#/config">去调整 →</a>
        <a class="btn" href="#/gap">看技能缺口 →</a>
      </div>
      <div class="card"><h3>最新反馈 <span class="tag">共 ${s.feedback.total} 条</span></h3>${fb}</div>
    </div>
  </div>`;
}
VIEWS.overview = async () => overviewHtml();

/* ============================ 个人履历（四大分类 · 证据强度） ============================ */
let PDRAFT = null;

/* 个人履历板块折叠：状态记在 localStorage，重渲染（增删条目）后恢复 */
const COLLAPSE_KEY = 'wb.profile.collapse.';
const isSecCollapsed = (id) => { try { return localStorage.getItem(COLLAPSE_KEY + id) === '1'; } catch (e) { return false; } };

/* 与 workbench/scoring.py 同一公式：强度分 + 落点分 + 量化分 */
const EV_LEVELS = {
  5: ['★★★★★', '可量化的项目结果', 50], 4: ['★★★★', '规模 / 复杂度上下文', 40],
  3: ['★★★', '角色与职责', 28], 2: ['★★', '外部验证', 18],
  1: ['★', '时长与频率', 8], 0: ['☆', '证书 / 课程', 4],
};
const GROUPS = {
  professional: ['专业技能', '可验证的方法与领域能力 —— 技能区主体，按目标岗位匹配度排序'],
  tools: ['工具与技术栈', '语言 / 框架 / 数据库 / 中间件 / 云与 DevOps'],
  soft: ['通用能力', '通过经历 bullet 证明；确需列出时带场景，最多 5 条'],
  credentials: ['语言与资质', '外语等级、证书、执照 —— 按含金量降序'],
};
const SOFT_LIMIT = 5;

function scoreOf(sk) {
  sk = sk || {};
  const lv = Math.max(0, Math.min(5, parseInt(sk.evidenceLevel, 10) || 0));
  const refs = (sk.projectRefs || []).filter((x) => String(x).trim()).length;
  const mets = (sk.metrics || []).filter((x) => String(x).trim()).length;
  const b = { 证据强度: EV_LEVELS[lv][2], 项目落点: Math.min(refs * 12, 30), 量化结果: Math.min(mets * 10, 20) };
  const score = Object.values(b).reduce((a, c) => a + c, 0);
  const tier = score >= 80 ? '强证据' : score >= 60 ? '较充分' : score >= 40 ? '一般' : score >= 20 ? '薄弱' : '待补证据';
  return { score, tier, stars: EV_LEVELS[lv][0], breakdown: b, refs, mets };
}
const tierChip = (sc) => `<span class="chip ${sc.score >= 60 ? 'ok' : sc.score >= 40 ? 'on' : 'bad'}">${sc.score} 分 · ${sc.tier}</span>`;

const LIST_SCHEMA = {
  education: { label: '教育经历', fields: [['school', '学校'], ['degree', '学位'], ['major', '专业'], ['start', '开始'], ['end', '结束']] },
  experiences: { label: '工作经历', fields: [['company', '公司'], ['role', '职位'], ['start', '开始'], ['end', '结束']], flags: [['remote', '远程']], lists: [['highlights', '主要工作（每行一条）']] },
  projects: { label: '项目经历', fields: [['name', '项目名称'], ['type', '类型'], ['period', '期间'], ['link', '链接']], lists: [['stack', '技术栈（每行一条）'], ['highlights', '项目亮点（每行一条）']] },
};
const blankSkill = (group, name = '') => ({
  name, group, cluster: group === 'tools' ? '语言' : group === 'soft' ? '协作' : group === 'credentials' ? '语言' : '系统设计',
  evidenceLevel: null, projectRefs: [], metrics: [], statement: '', scenario: '',
});

/* 证据强度自动标定：与 scoring.py 金字塔一致（5→1 取最强），保存时对未标定的技能推断 */
function inferLevel(st) {
  st = st || '';
  // ★★★★★ 可量化项目结果：性能毫秒 / 倍率 / 百分比 / 前后对比（800ms→120ms、+12%、降 60%）
  if (/(\d+(?:\.\d+)?\s*(?:ms|倍|%)|->|→|\d+(?:\.\d+)?\s*(?:提升|降低|减少|增加|优化|压缩|节省))/.test(st)) return 5;
  // ★★★★ 规模/复杂度上下文：日活 500 万、QPS 3 万、200 节点集群
  if (/(\d+(?:\.\d+)?\s*(?:万|亿|百万|千万|QPS|节点|日活|峰值|集群|日均|台|条|用户|请求|并发))/.test(st)) return 4;
  // ★★★ 角色与职责
  if (/(主导|独立|负责|搭建|设计|落地|重构|从0到1|从零)/.test(st)) return 3;
  // ★★ 外部验证
  if (/(开源|PR|专利|竞赛|获奖)/.test(st)) return 2;
  // ★ 时长与频率
  return 1;
}

function blank(k) {
  if (k === 'education') return { school: '', degree: '', major: '', start: '', end: '' };
  if (k === 'experiences') return { company: '', role: '', start: '', end: '', remote: false, highlights: [], subProjects: [] };
  return { name: '', type: '', period: '', link: '', stack: [], highlights: [], rank: 0 };
}
const blankSubProject = () => ({ name: '', period: '', stack: [], highlights: [], rank: 0 });

/* 核心项目 rank：0=不展示，1-5=展示顺序。rank 全局唯一（个人项目 + 所有工作经历的子项目共用同一把 1-5 的椅子）。 */
function usedRanks() {
  const used = new Set();
  (PDRAFT.projects || []).forEach((p) => { const r = parseInt(p.rank, 10) || 0; if (r > 0) used.add(r); });
  (PDRAFT.experiences || []).forEach((w) => (w.subProjects || []).forEach((sp) => { const r = parseInt(sp.rank, 10) || 0; if (r > 0) used.add(r); }));
  return used;
}
/* 单个档位行：当前选中 → 紫底白字；已占用 → 浅灰背景（原生 select 不渲染 option 背景，改用自定义浮层） */
function rankRowHtml(r, cur, used) {
  const taken = r > 0 && used.has(r) && r !== cur;
  const sel = r === cur;
  const cls = 'rp-row' + (sel ? ' on' : '') + (taken ? ' taken' : '');
  const label = r === 0 ? '不展示' : '第 ' + r + ' 个' + (sel ? '（当前）' : '');
  return '<div class="' + cls + '" data-rankval="' + r + '">' + label + '</div>';
}
/* 自定义 rank 下拉（浮层）：hidden input 供 syncProfileFromDom 回写；行点击走插入式顺延 */
function rankPicker(path, current, used) {
  const cur = parseInt(current, 10) || 0;
  return '<span class="rankpick" data-rank="1" data-rpath="' + path + '" tabindex="0">'
    + '<input type="hidden" data-p="' + path + '" data-num="1" value="' + cur + '">'
    + '<span class="rp-val">' + (cur > 0 ? '第 ' + cur + ' 个' : '不展示') + '</span>'
    + '<span class="rp-caret">▾</span>'
    + '<span class="rp-list" style="display:none">'
    + [0, 1, 2, 3, 4, 5].map((r) => rankRowHtml(r, cur, used)).join('')
    + '</span></span>';
}
/* 内容区的 rank 设置（带说明） */
function rankSelect(path, current, used) {
  const cur = parseInt(current, 10) || 0;
  return '<div class="field" style="margin-bottom:6px">'
    + '<label>核心项目排名</label>'
    + rankPicker(path, cur, used)
    + '<span class="small muted">0=不进入简历核心项目区；灰色档位已被占用，点选即替换并自动顺延</span></div>';
}

/* 折叠标题栏的 rank 控件：徽标 + 自定义小下拉（可直接设置） */
function titleRankControl(path, rank, used) {
  const cur = parseInt(rank, 10) || 0;
  return '<span style="display:inline-flex;align-items:center;gap:5px">'
    + rankPicker(path, cur, used) + '</span>';
}
/* 插入式设置 rank：目标选到已占用档位时，被占项目及之后整体顺延 +1；顺延超过 5 的移出核心区（设为 0）。 */
function shiftRankInto(path, value) {
  const cur = Number(getPath(PDRAFT, path)) || 0;
  const v = Number(value) || 0;
  if (v === cur) return;
  if (v <= 0) { setPath(PDRAFT, path, 0); return; }
  const others = [];
  (PDRAFT.projects || []).forEach((p, i) => others.push({ path: 'projects.' + i + '.rank', rank: parseInt(p.rank, 10) || 0 }));
  (PDRAFT.experiences || []).forEach((w, ei) => (w.subProjects || []).forEach((sp, si) => {
    others.push({ path: 'experiences.' + ei + '.subProjects.' + si + '.rank', rank: parseInt(sp.rank, 10) || 0 });
  }));
  // 被占档位及之后的项目顺延；从大到小处理，避免连锁覆盖错位
  others.filter((it) => it.path !== path && it.rank >= v && it.rank > 0)
    .sort((a, b) => b.rank - a.rank)
    .forEach((it) => setPath(PDRAFT, it.path, it.rank + 1 > 5 ? 0 : it.rank + 1));
  setPath(PDRAFT, path, v);
}
/* 任一 rank 控件变更后同步所有控件（标题栏徽标 + 浮层选项 + 占用置灰），保持折叠/展开状态不丢失 */
function refreshRankUI() {
  const used = usedRanks();
  $$('.rankpick').forEach((pk) => {
    const path = pk.dataset.rpath;
    const cur = Number(getPath(PDRAFT, path)) || 0;
    const val = pk.querySelector('.rp-val');
    if (val) val.textContent = cur > 0 ? '第 ' + cur + ' 个' : '不展示';
    const hid = pk.querySelector('input[data-p]');
    if (hid) hid.value = String(cur);
    const list = pk.querySelector('.rp-list');
    if (list) {
      const wasOpen = list.style.display !== 'none';
      list.innerHTML = [0, 1, 2, 3, 4, 5].map((r) => rankRowHtml(r, cur, used)).join('');
      list.style.display = wasOpen ? 'block' : 'none';
    }
  });
  $$('[data-rtag]').forEach((el) => {
    const cur = Number(getPath(PDRAFT, el.dataset.rtag)) || 0;
    el.className = 'rtag ' + (cur > 0 ? 'on' : 'off');
  });
}

function listEditor(key, items, secId) {
  const sc = LIST_SCHEMA[key];
  const used = usedRanks();   // 全局已占用 rank（个人项目 + 工作子项目共用），渲染下拉时置灰
  // 工作经历：公司/职位一行(g2)，开始/结束时间同一行(g2)
  const fieldsHtmlFor = (it, i) => {
    if (key === 'experiences') {
      return `
        <div class="grid g2" style="margin-bottom:6px">
          <div class="field"><label>公司</label><input data-p="${key}.${i}.company" value="${esc(it.company || '')}"></div>
          <div class="field"><label>职位</label>
            <div style="display:flex;align-items:center;gap:10px">
              <input data-p="${key}.${i}.role" value="${esc(it.role || '')}" style="flex:1">
              <label class="chip ${it.remote ? 'ok' : ''}" style="cursor:pointer;white-space:nowrap"><input type="checkbox" data-p="${key}.${i}.remote" ${it.remote ? 'checked' : ''} style="width:auto"> 远程</label>
            </div>
          </div>
        </div>
        <div class="grid g2" style="margin-bottom:6px">
          <div class="field"><label>开始时间</label><input data-p="${key}.${i}.start" value="${esc(it.start || '')}" placeholder="2024.03"></div>
          <div class="field"><label>结束时间</label><input data-p="${key}.${i}.end" value="${esc(it.end || '')}" placeholder="2026.03"></div>
        </div>`;
    }
    return `<div class="grid g3">
        ${sc.fields.map(([f, lb]) => `<div class="field" style="margin-bottom:6px"><label>${lb}</label>
          <input data-p="${key}.${i}.${f}" value="${esc(it[f] || '')}"></div>`).join('')}
        ${(sc.flags || []).map(([f, lb]) => `<div class="field" style="margin-bottom:6px"><label>${lb}</label>
          <label class="chip ${it[f] ? 'ok' : ''}" style="cursor:pointer"><input type="checkbox" data-p="${key}.${i}.${f}" ${it[f] ? 'checked' : ''} style="width:auto"> ${lb}</label></div>`).join('')}
      </div>`;
  };
  // 工作经历内嵌的「主要项目」子列表（可多个，结构同标准项目：名称/期间/技术栈/亮点）
  const subProjectsHtml = (exp, ei) => {
    const subs = exp.subProjects || [];
    const cards = subs.map((sp, si) => `
      <details style="border:1px dashed var(--line);border-radius:8px;margin:6px 0;background:#fff">
        <summary style="padding:6px 10px;cursor:pointer;display:flex;justify-content:space-between;align-items:center;list-style:none">
          <b class="small" style="font-weight:500">${esc(sp.name || `子项目 #${si+1}`)}</b>
          <span style="display:flex;gap:4px;align-items:center">
            ${sp.period ? `<span class="small muted" style="margin-right:6px">${esc(sp.period)}</span>` : ''}
            ${titleRankControl(`experiences.${ei}.subProjects.${si}.rank`, sp.rank, used)}
            <label class="chip ${sp.showInWork ? 'ok' : ''}" style="cursor:pointer;white-space:nowrap;font-size:11px" title="勾选后该子项目会在 PDF 工作经历区块展示（不进核心项目经历区）">
              <input type="checkbox" data-p="experiences.${ei}.subProjects.${si}.showInWork" ${sp.showInWork ? 'checked' : ''} style="width:auto"> 工作经历展示</label>
            <button class="sm ghost" data-delsub="${ei}:${si}">删除</button>
          </span>
        </summary>
        <div style="padding:4px 10px 8px">
          <div class="grid g2" style="margin-bottom:6px">
            <div class="field"><label>项目名称</label><input data-p="experiences.${ei}.subProjects.${si}.name" value="${esc(sp.name || '')}"></div>
            <div class="field"><label>期间</label><input data-p="experiences.${ei}.subProjects.${si}.period" value="${esc(sp.period || '')}" placeholder="2024.03 - 2025.06"></div>
          </div>
          <div class="field" style="margin-bottom:6px"><label>技术栈</label>
            <textarea data-p="experiences.${ei}.subProjects.${si}.stack" data-list="1" style="min-height:44px">${esc((sp.stack || []).join('\n'))}</textarea></div>
          <div class="field" style="margin-bottom:6px"><label>项目亮点（每行一条）</label>
            <textarea data-p="experiences.${ei}.subProjects.${si}.highlights" data-list="1" style="min-height:60px">${esc((sp.highlights || []).join('\n'))}</textarea></div>
        </div>
      </details>`).join('');
    return `<div style="margin:8px 0 4px;padding-top:8px;border-top:1px dashed var(--line)">
      <div class="row" style="justify-content:space-between;margin-bottom:4px">
        <span class="small" style="font-weight:600">主要项目（${subs.length}）</span>
        <button class="sm ghost" data-addsub="${ei}" title="在这家公司下添加一个主要项目">+ 添加项目</button>
      </div>
      ${cards || '<div class="small muted" style="padding:4px 0">这家公司下的核心项目可单独添加，按项目写技术栈与亮点。</div>'}
    </div>`;
  };
  const rows = (items || []).map((it, i) => {
    // 折叠标题：项目经历显示项目名；工作经历显示公司名+职位；教育显示学校
    let title = '';
    if (key === 'projects') title = it.name || `项目 #${i+1}`;
    else if (key === 'experiences') title = `${it.company || ''} · ${it.role || ''}`.replace(/^ · | ·$/g, '') || `工作 #${i+1}`;
    else title = `${it.school || ''} · ${it.degree || ''}`.replace(/^ · | ·$/g, '') || `教育 #${i+1}`;
    const sub = [it.period, it.type, it.start && it.end ? `${it.start} - ${it.end}` : ''].filter(Boolean).join(' · ');
    return `
    <details class="item-card" id="${key}-${i}" open style="border:1px solid var(--line);border-radius:10px;margin-bottom:8px;background:#fcfdfe">
      <summary style="padding:9px 13px;cursor:pointer;display:flex;justify-content:space-between;align-items:center;list-style:none">
        <b class="small">${esc(title)}</b>
        <span style="display:flex;gap:4px;align-items:center">
          ${sub ? `<span class="small muted" style="margin-right:6px">${esc(sub)}</span>` : ''}
          ${key === 'projects' ? titleRankControl(`${key}.${i}.rank`, it.rank, used) : ''}
          <button class="sm ghost" data-delitem="${key}:${i}">删除</button>
        </span>
      </summary>
      <div style="padding:4px 13px 11px">
      ${fieldsHtmlFor(it, i)}
      ${key === 'projects' ? rankSelect(`${key}.${i}.rank`, it.rank, used) : ''}
      ${key === 'experiences' ? subProjectsHtml(it, i) : ''}
      ${(sc.lists || []).map(([f, lb]) => {
        // 所有 list 字段统一 textarea 每行一个（技术栈/亮点都是），不再单行顿号分隔
        return `<div class="field" style="margin-bottom:6px"><label>${lb}</label>
        <textarea data-p="${key}.${i}.${f}" data-list="1" data-count="1" style="min-height:${f === 'highlights' ? 72 : f === 'techstack' ? 44 : 60}px">${esc((it[f] || []).join('\n'))}</textarea>
        <div class="field-foot"><span class="ccount" title="实际字数/推荐字数">${esc(((it[f] || []).join('\n').trim().length))}/40</span></div></div>`;
      }).join('')}
      </div>
    </details>`;
  }).join('');
  const cid = secId || '';
  const foldable = cid ? ` collapsible${isSecCollapsed(cid) ? ' collapsed' : ''}` : '';
  return `<div class="card${foldable}" id="${cid}" ${cid ? `data-collapse="${cid}"` : ''}><h3 class="sec-head" ${cid ? `data-toggle="${cid}"` : ''}>${sc.label} <span class="tag">${(items || []).length} 条</span>${cid ? '<span class="chev" aria-hidden="true">▾</span>' : ''}</h3>
    <div class="sec-body">
    ${rows || '<div class="empty">还没有记录</div>'}
    <button id="add-${key}">+ 添加${sc.label}</button>
    </div></div>`;
}

const SKILL_PLACEHOLDER = {
  professional: '如：系统架构设计、高并发性能优化（逗号或换行一条）',
  tools: '如：Python、Java、K8s（逗号或换行一条）',
  soft: '如：跨团队协作、项目管理（逗号或换行一条）',
  credentials: '如：英语6级、PMP（逗号或换行一条）',
};

/* 技能区：四大分类按行罗列，编辑时展开；证据细节交给「岗位匹配」面板 */
function skillsSection(p) {
  const all = p.skills || [];
  const byGroup = (g) => all.map((s, i) => ({ s, i })).filter((x) => (x.s.group || 'professional') === g);
  const idxSorted = (g) => {
    const arr = byGroup(g);
    if (g === 'professional') arr.sort((a, b) => ((b.s._match || {}).coverage || 0) - ((a.s._match || {}).coverage || 0) || scoreOf(b.s).score - scoreOf(a.s).score);
    if (g === 'credentials') arr.sort((a, b) => (b.s.evidenceLevel || 0) - (a.s.evidenceLevel || 0));
    return arr;
  };
  const groupCard = (g, extra) => {
    const arr = idxSorted(g);
    const meta = GROUPS[g];
    const chips = arr.length ? arr.map((x) => `<span class="chip slim ${x.s.group === 'tools' ? 'on' : 'mute'}">${esc(x.s.name)}</span>`).join('') : '';
    const keepNote = g === 'soft' ? '；已有条目的场景说明会自动保留' : '；已有的证据与项目落点会自动保留';
    return `<details class="card skill-group" id="sec-${g}" ${arr.length ? '' : 'open'}>
      <summary>
        <span class="glabel">${meta[0]}</span>
        <span class="gitems">${chips || '<span class="small muted">未填写 —— 点「展开编辑」添加</span>'}</span>
        <span class="chev">${arr.length ? '展开编辑' : '去填写'}</span>
      </summary>
      <div class="g-edit">
        ${extra || ''}
        <div class="field"><label>${meta[0]}清单 <span class="small muted">（逗号 / 换行分隔，每行一条${keepNote}）</span></label>
          <textarea data-skills="${g}" style="min-height:${Math.max(88, arr.length * 24 + 44)}px;line-height:1.7" placeholder="${esc(SKILL_PLACEHOLDER[g])}">${esc(arr.map((x) => x.s.name).join('\n'))}</textarea></div>
      </div>
    </details>`;
  };
  const envRow = `<div class="field" style="margin-bottom:8px"><label>日常工作环境</label>
    <input data-p="skillEnvironment" value="${esc(p.skillEnvironment || '')}" placeholder="如：Linux / Git / Docker / Nginx"></div>`;
  const soft = byGroup('soft');
  const softWarn = soft.length > SOFT_LIMIT
    ? `<div class="small" style="color:var(--bad);margin-bottom:8px">通用能力已列 ${soft.length} 条，规范要求 ≤${SOFT_LIMIT} 条且必须带场景。</div>` : '';
  return `
  <div class="card skill-summary"><h3>技能区 <span class="tag">四大分类</span></h3>
    ${groupCard('professional')}
    ${groupCard('tools', envRow)}
    ${groupCard('soft', softWarn)}
    ${groupCard('credentials')}
  </div>`;
}

/* 目标岗位管理：可多个目标，选中一个作为简历标题与技能分析口径（搜岗页顶部，最大前提） */
function targetsHtml(p, opts = {}) {
  const ts = p.targets || [];
  const active = p.activeTarget || (ts[0] && ts[0].id) || '';
  const cur = ts.find((t) => t.id === active) || ts[0] || { title: '' };
  const rows = ts.map((t) => `
    <div data-trow data-tid="${esc(t.id)}" style="border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin-bottom:8px;background:#fcfdfe">
      <div class="row" style="gap:8px">
        <label class="small" style="display:flex;align-items:center;gap:4px;white-space:nowrap"><input type="radio" name="tactive" data-tactive value="${esc(t.id)}" ${t.id === active ? 'checked' : ''}>选中</label>
        <input data-ttitle value="${esc(t.title || '')}" placeholder="如：Agent系统工程师" style="flex:1;min-width:120px">
        <button class="sm ghost" data-tdel="${esc(t.id)}">删除</button>
      </div>
      <div class="small muted" style="margin-top:8px">搜索关键词 <span class="small muted">（逗号分隔，采集/筛选/简报都按它来）</span></div>
      <input data-tkw value="${esc((t.keywords || []).join('，'))}" placeholder="如：Agent应用工程师，AI Agent工程师" style="width:100%;margin-top:3px">
    </div>`).join('');
  return `<details id="targetD"${opts.open ? ' open' : ''}>
    <summary style="cursor:pointer"><b>${esc(cur.title || '（未命名）')}</b>
      <span class="small muted">${opts.open ? '｜收起（共 ' + ts.length + ' 个目标）' : '｜展开管理/切换（共 ' + ts.length + ' 个目标）'}</span></summary>
    <div id="targetList" style="margin-top:8px">${rows}
      <button id="addTarget" class="sm">+ 添加目标</button></div>
  </details>`;
}

function profileHtml() {
  const p = PDRAFT || {};
  const skills = p.skills || [];
  const cnt = (g) => skills.filter((x) => (x.group || 'professional') === g).length;
  const sumPos = p.summaryPosition || ((!p.summaryResult && !p.summaryRarity) ? (p.summary || '') : '');
  const sumRes = p.summaryResult || '';
  const sumRar = p.summaryRarity || '';
  const TOC = [
    ['sec-basic', '基本信息'],
    ['sec-summary', '个人简介'],
    ['sec-education', '教育经历'],
    ['sec-experiences', '工作经历'],
    ['sec-projects', '项目经历'],
    ['sec-professional', '专业技能'],
    ['sec-tools', '工具与技术栈'],
    ['sec-soft', '通用能力'],
    ['sec-credentials', '语言与资质'],
    ['sec-json', '高级编辑'],
  ];
  const tocItem = (id, label, n) => `<a href="#/profile" data-jump="${id}" class="${n === 0 ? 'zero' : ''}">${label}${n != null ? ` <b>${n}</b>` : ''}</a>`;
  const tocSub = (id, label) => `<a href="#/profile" data-jump="${id}" class="toc-sub">${esc(label)}</a>`;
  const toc = [
    tocItem('sec-basic', '基本信息'),
    tocItem('sec-summary', '个人简介'),
    tocItem('sec-education', '教育经历', (p.education || []).length),
    tocItem('sec-experiences', '工作经历', (p.experiences || []).length),
    ...(p.experiences || []).map((w, i) => tocSub(`experiences-${i}`, `${w.company || `经历 #${i+1}`} · ${w.role || ''}`)),
    tocItem('sec-projects', '项目经历', (p.projects || []).length),
    ...(p.projects || []).map((pr, i) => tocSub(`projects-${i}`, pr.name || `项目 #${i+1}`)),
    tocItem('sec-professional', '技能', cnt('professional') + cnt('tools') + cnt('soft') + cnt('credentials')),
    tocItem('sec-json', '高级编辑'),
  ].join('');
  return `
  <div class="profile-layout">
    <div class="profile-main">
      <div class="card collapsible${isSecCollapsed('sec-basic') ? ' collapsed' : ''}" id="sec-basic" data-collapse="sec-basic">
        <h3 class="sec-head" data-toggle="sec-basic">基本信息 <span class="tag">这份履历是简历生成与技能匹配的唯一事实来源；字段旁眼睛图标控制是否出现在 PDF 上</span><span class="chev" aria-hidden="true">▾</span></h3>
        <div class="sec-body">
          ${(() => {
            const vis = p.contactVisibility || {};
            const eye = (k, defaultOn=true) => {
              const on = vis[k] !== undefined ? !!vis[k] : defaultOn;
              // 扁平线条 SVG icon：眼睛（显示）/ 眼睛加斜杠（隐藏）
              const svgOn = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>';
              const svgOff = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>';
              return `<span class="vis-eye" data-vis="${k}" title="${on ? '在简历上显示（点击隐藏）' : '不在简历上显示（点击显示）'}" style="cursor:pointer;margin-left:6px;display:inline-flex;align-items:center;vertical-align:middle;color:${on?'#2b6cb0':'#a0aec0'}">${on ? svgOn : svgOff}</span>`;
            };
            const visWrap = (k, inner) => `<span class="vis-wrap" data-vis="${k}" style="cursor:pointer;display:inline-flex;align-items:center;vertical-align:middle">${inner}</span>`;
            return `<div class="grid g3">
            <div class="field"><label>姓名</label><input data-p="name" value="${esc(p.name)}"></div>
            <div class="field"><label>性别${eye('gender', true)}</label>
              <select data-p="gender" style="padding:7px 10px;border:1px solid #d0d5db;border-radius:6px;background:#fff">
                ${['', '男', '女'].map((g) => `<option value="${g}" ${(p.gender||'')===g?'selected':''}>${g||'未填'}</option>`).join('')}
              </select></div>
            <div class="field"><label>年龄${eye('age', true)}</label><input data-p="age" value="${esc(p.age||'')}" placeholder="如 32"></div>
            <div class="field"><label>求职方向（简历标题）</label>
              <input value="${esc(p.title || '')}" disabled style="background:#f5f6f7;color:#555">
              <div class="small muted" style="margin-top:2px">由「搜岗 → 目标岗位」决定，在搜岗页管理</div></div>
            <div class="field"><label>电话${eye('phone', true)}</label><input data-p="phone" value="${esc(p.phone)}"></div>
            <div class="field"><label>邮箱${eye('email', true)}</label><input data-p="email" value="${esc(p.email)}"></div>
            <div class="field"><label>城市${eye('city', true)}</label><input data-p="city" value="${esc(p.city)}"></div>
            <div class="field"><label>工作年限${eye('years', true)}</label><input data-p="years" data-num="1" value="${esc(p.years)}"></div>
            <div class="field"><label>GitHub / 主页${eye('github', true)}</label><input data-p="github" value="${esc(p.github)}"></div>
          </div>`;
          })()}
        </div>
      </div>
      <div class="card collapsible${isSecCollapsed('sec-summary') ? ' collapsed' : ''}" id="sec-summary" data-collapse="sec-summary">
        <h3 class="sec-head" data-toggle="sec-summary">个人简介 <span class="tag">定位 / 成果 / 稀缺 三段式，面向 JD 定制</span><span class="chev" aria-hidden="true">▾</span></h3>
        <div class="sec-body">
          <div class="field"><label>定位 <span class="small muted">你是谁 · 年限 · 公司背书 · 领域稀缺性</span></label>
            <input data-p="summaryPosition" data-count="1" value="${esc(sumPos)}" placeholder="如：8 年后端研发，近 2 年专注 Agent 系统工程">
            <div class="field-foot"><span class="ccount" title="实际字数/推荐字数">${esc(sumPos.trim().length)}/40</span></div></div>
          <div class="field"><label>成果 <span class="small muted">1-2 个量化结果</span></label>
            <input data-p="summaryResult" data-count="1" value="${esc(sumRes)}" placeholder="如：网关单节点吞吐提升 5-10 倍">
            <div class="field-foot"><span class="ccount" title="实际字数/推荐字数">${esc(sumRes.trim().length)}/40</span></div></div>
          <div class="field"><label>稀缺 <span class="small muted">稀缺组合 · 为什么是你 · 差异化定位 · JD 匹配</span></label>
            <input data-p="summaryRarity" data-count="1" value="${esc(sumRar)}" placeholder="如：底层性能优化 + Agent 可观测的稀缺组合">
            <div class="field-foot"><span class="ccount" title="实际字数/推荐字数">${esc(sumRar.trim().length)}/40</span></div></div>
        </div>
      </div>
      ${listEditor('education', p.education, 'sec-education')}
      ${listEditor('experiences', p.experiences, 'sec-experiences')}
      ${listEditor('projects', p.projects, 'sec-projects')}
      ${skillsSection(p)}
      <details class="card" id="sec-json"><summary><b>高级编辑</b> <span class="small muted">直接改 JSON（一般用不到）</span></summary>
        <textarea id="rawProfile" style="min-height:200px;margin-top:10px" class="mono">${esc(JSON.stringify(PDRAFT, null, 1))}</textarea>
        <div class="row" style="margin-top:8px"><button id="saveRaw">保存 JSON</button></div>
      </details>
      <div class="savebar">
        <button class="primary" id="saveProfile" style="padding:8px 20px">保存</button>
      </div>
    </div>
    <aside class="profile-toc">
      <div class="toc-title">大纲</div>
      ${toc}
      <div class="toc-gen">
        <div class="toc-title" style="margin-top:14px">生成简历</div>
        <select id="genTarget" style="width:100%;padding:6px 8px;border:1px solid #d0d5db;border-radius:6px;background:#fff;font-size:12px" title="目标岗位（决定简历标题）">
          ${(p.targets || []).map((t) =>
            `<option value="${esc(t.id)}" ${t.id === p.activeTarget ? 'selected' : ''}>${esc(t.title)}</option>`).join('')}
        </select>
        <select id="genTpl" style="width:100%;padding:6px 8px;margin-top:6px;border:1px solid #d0d5db;border-radius:6px;background:#fff;font-size:12px" title="简历模板">
          <option value="">默认</option>
        </select>
        <button id="genResume" class="primary" style="width:100%;margin-top:8px;padding:8px" title="按所选目标岗位+模板，基于当前履历直接生成 PDF（不调 LLM、不编造）">生成简历</button>
      </div>
    </aside>
  </div>`;
}

VIEWS.profile = async () => {
  PDRAFT = await api('/profile');
  return profileHtml();
};

/* 城市行 / 关键词 chip 的行内渲染（增删后局部重渲染用） */
function cityRowHtml(cities) {
  return (cities || []).map((x, i) => {
    const ok = x.resolved !== false && x.code;
    return `<tr>
      <td><input data-c="cities.${i}.name" value="${esc(x.name || '')}" placeholder="只填城市名，如 杭州"></td>
      <td><span class="chip ${ok ? 'ok' : 'bad'}">${ok ? '已自动匹配' : '待匹配'}</span></td>
      <td class="adv" style="display:none"><input data-c="cities.${i}.code" value="${esc(x.code || '')}" placeholder="自动补全"></td>
      <td><input data-c="cities.${i}.priority" type="number" min="1" value="${esc(x.priority != null ? x.priority : 9)}"></td>
      <td><button class="sm ghost" data-cdel="${i}">删</button></td></tr>`;
  }).join('');
}

async function renderSearchConfig() {
  const c = await api('/config');
  const rts = ['校招', '社招'].map((t) =>
    `<label class="chip ${(c.recruit_types || []).includes(t) ? 'ok' : ''}" style="cursor:pointer">
      <input type="checkbox" data-rt="${esc(t)}" ${(c.recruit_types || []).includes(t) ? 'checked' : ''} style="width:auto"> ${esc(t)}</label>`).join('');
  const acts = ['刚刚活跃', '今日活跃', '3日内活跃', '本周活跃'].map((a) =>
    `<label class="chip ${(c.activity_preference || []).includes(a) ? 'ok' : ''}" style="cursor:pointer">
      <input type="checkbox" data-act="${esc(a)}" ${(c.activity_preference || []).includes(a) ? 'checked' : ''} style="width:auto"> ${esc(a)}</label>`).join('');
  const rtTxt = (c.recruit_types || []).join('、') || '不限';
  return `
  <div class="card drawer">
    <div class="drawer-head">
      <div>
        <b>搜岗参数</b>
        <div class="small muted" style="margin-top:2px">城市 ${(c.cities || []).length} 个 ·
          ${esc(c.salary?.min)}-${esc(c.salary?.max)}${esc(c.salary?.unit || 'K')} · 招聘类型 ${esc(rtTxt)} ·
          <b>关键词在「目标岗位」里设置</b></div>
      </div>
      <button id="cfgToggle" class="sm">展开编辑 ▾</button>
    </div>
    <div id="cfgBody" class="drawer-body" style="display:none">
      <div class="card"><h3>目标城市 <span class="tag">只填城市名，城市码系统自动补全</span></h3>
        <div class="tablewrap" style="max-height:none"><table><thead><tr><th>城市</th><th>匹配</th><th class="adv" style="display:none">城市码（高级）</th><th>优先级</th><th></th></tr></thead>
        <tbody id="cityBody">${cityRowHtml(c.cities)}</tbody></table></div>
        <div class="row" style="margin-top:10px"><button id="addCity">+ 添加城市</button>
          <label class="chip" style="cursor:pointer"><input type="checkbox" id="showAdv" style="width:auto"> 高级（显示城市码）</label>
          <span class="small muted">已内置 46 个常用城市，未收录的城市会标「待匹配」，Agent 会自动现查。</span></div>
      </div>
      <div class="card"><h3>硬性筛选</h3>
        <div class="grid g3">
          <div class="field"><label>薪资下限 (K)</label><input id="salMin" type="number" value="${esc(c.salary?.min)}"></div>
          <div class="field"><label>薪资上限 (K)</label><input id="salMax" type="number" value="${esc(c.salary?.max)}"></div>
          <div class="field"><label>本批投递数量</label><input id="batch" type="number" value="${esc(c.batch_size)}"></div>
        </div>
        <div class="small muted" style="margin-top:4px">搜索关键词在顶部「目标岗位」里设置，每个目标各自独立</div>
        <div class="field"><label>招聘类型（不勾选 = 不限）</label><div class="chips">${rts}</div></div>
        <div class="field"><label>招聘者活跃度偏好（优先级从高到低）</label><div class="chips">${acts}</div></div>
      </div>
      <div class="drawer-foot">
        <span class="small muted" style="margin-right:auto">修改后点右下角「保存配置」统一生效</span>
        <button id="reloadConfig">重新载入</button>
        <button class="primary" id="saveConfig">保存配置</button>
      </div>
    </div>
  </div>`;
};


let CUR = {};   // 当前路由参数（供 hooks 使用）

/* 投递与反馈：置顶策略，下面接投递记录与反馈录入 */
async function renderSkillEditor() {
  const r = await api('/resume/skill').catch(() => ({ content: '# 加载失败' }));
  return `
  <div class="card"><h3>简历撰写规范 <span class="tag">Markdown · 完整 Skill 内容，可编辑保存 · LLM 定制简历时按此规范产出</span></h3>
    <p class="small muted" style="margin-bottom:8px">本文件即 <code>data/resume_skill.md</code>，内容源自 <code>skills/boss-zhipin-apply/SKILL.md</code>。
    修改后点「保存」写盘；LLM 按 JD 定制简历时会读这份规范。</p>
    <textarea id="skillContent" spellcheck="false" style="width:100%;min-height:560px;font-family:ui-monospace,Menlo,monospace;font-size:12px;line-height:1.6;padding:12px;border:1px solid #d0d5db;border-radius:6px">${esc(r.content || '')}</textarea>
    <div class="row" style="margin-top:8px">
      <button id="skillSave" class="primary">保存规范</button>
      <span id="skillMsg" class="small muted"></span>
    </div>
  </div>`;
}
async function renderTplEditor() {
  const tpl = await api('/resume/templates').catch(() => ({ templates: [{ name: 'resume.html', builtin: true }], default: 'resume.html' }));
  return `
  <div class="card"><h3>简历模板编辑器 <span class="tag">预览即编辑 · 拖拽区块调序 · 实时保存</span></h3>
    <div class="row" style="margin-bottom:6px"><span class="small muted">模板</span>
      <select id="tplSelect" style="flex:1">
        ${(tpl.templates || []).map((t) => `<option value="${esc(t.name)}" ${t.name === tpl.default ? 'selected' : ''}>${esc(t.name)}${t.builtin ? '（内置）' : '（自定义）'}</option>`).join('')}
      </select>
      <button id="tplSetDefault" class="sm">设为默认</button>
      <button id="tplDelete" class="sm" title="删除当前模板（内置模板不可删）">删除模板</button>
      <button id="tplRestore" class="sm" title="找回被移除的区块">恢复全部区块</button>
      <span class="small muted" style="margin-left:8px">字号</span>
      <button id="tplFontDown" class="sm" title="所有 font-size 同比例 ×0.9">A-</button>
      <button id="tplFontUp" class="sm" title="所有 font-size 同比例 ×1.1">A+</button>
    </div>
    <p class="small muted" style="margin-bottom:8px">占位符：<span class="mono">{{HEADER}} {{SUMMARY}} {{SKILLS}} {{PROJECTS}} {{WORK}} {{EDUCATION}} {{OTHER}}</span>。
    头部固定置顶；在预览里<b>直接拖动区块</b>调整顺序，区块右上角 <b>×</b> 移除（「恢复全部区块」找回）；
    <b>点击区块</b>，右侧调试面板查看并修改该区块的样式。</p>
    <div style="display:flex;gap:12px;align-items:stretch">
      <iframe id="tplPreview" title="模板结构预览（可拖拽/点击编辑样式）" style="flex:1;min-width:0;height:520px;border:1px solid #e5e7eb;background:#fff;border-radius:4px"></iframe>
      <aside id="tplStylePanel" style="width:370px;flex:none;display:flex;flex-direction:column;overflow:auto;border:1px solid #e5e7eb;border-radius:6px;background:#fafbfc">
        <div style="display:flex;align-items:center;gap:8px;padding:8px 10px;background:#f1f5f9;border-bottom:1px solid #e5e7eb">
          <b class="small">区块样式</b><span id="tplStyleTitle" class="small muted" style="flex:1">点击左侧预览中的区块查看</span>
          <button id="tplStyleClose" class="sm" title="收起面板">×</button>
        </div>
        <div style="padding:8px 10px;display:flex;flex-direction:column">
          <div class="small muted" style="margin-bottom:4px">样式 JSON：<span id="tplStyleHint">标题 h2、正文、小标题、要点列表等全部规则，改完点「应用样式」写回</span></div>
          <textarea id="tplStyleJson" rows="16" spellcheck="false" style="width:100%;min-height:220px;font-family:ui-monospace,Menlo,monospace;font-size:11px;line-height:1.5"></textarea>
          <div class="row" style="margin-top:6px">
            <button id="tplStyleApply" class="sm primary">应用样式</button>
            <span class="small muted" id="tplStyleCount"></span>
          </div>
        </div>
      </aside>
    </div>
    <div class="row" style="margin-top:8px">
      <input id="tplName" placeholder="新模板名（无需填 .html，留空自动生成副本名）" style="flex:1">
      <button id="tplSave" class="sm primary">保存</button>
      <button id="tplSaveAs" class="sm">另存</button>
    </div>
    <p class="small muted" style="margin-top:6px">「保存」覆盖当前模板（内置模板会被用户版覆盖优先）；「另存」写入新模板文件，可在下拉选中。</p>
  </div>`;
}

VIEWS.strategy = async () => {
  const tab = (CUR.tab || 'policy');   // policy | template | feedback
  const tabs = `
  <div class="tabs">
    <a class="tab ${tab === 'policy' ? 'on' : ''}" href="#/strategy">策略</a>
    <a class="tab ${tab === 'template' ? 'on' : ''}" href="#/strategy?tab=template">简历模板</a>
    <a class="tab ${tab === 'skill' ? 'on' : ''}" href="#/strategy?tab=skill">撰写规范</a>
    <a class="tab ${tab === 'feedback' ? 'on' : ''}" href="#/strategy?tab=feedback">反馈</a>
    <span class="sp"></span>
  </div>`;
  if (tab === 'template') return tabs + await renderTplEditor();
  if (tab === 'skill') return tabs + await renderSkillEditor();
  if (tab === 'feedback') return tabs + '<div class="sectionhead"><span class="num">1</span>投递记录与反馈 <span class="tag">状态流转与效果评估</span></div>' + await renderApplications();
  return tabs + '<div class="sectionhead"><span class="num">1</span>投递策略 <span class="tag">周期、数量、时间窗、暂停条件 —— Agent 必须遵守</span></div>' + await renderStrategyForm();
};

HOOKS.strategy = () => {
  const tab = (CUR.tab || 'policy');
  if (tab === 'template') { HOOKS.tplEditor?.(); return; }
  if (tab === 'skill') {
    const btn = $('#skillSave');
    if (btn) btn.onclick = async () => {
      const content = ($('#skillContent') || {}).value || '';
      btn.disabled = true; btn.textContent = '保存中…';
      try {
        const r = await api('/resume/skill', { method: 'PUT', body: { content } });
        $('#skillMsg').textContent = `已保存（${r.bytes} 字符）`;
        toast('撰写规范已保存');
      } catch (e) { $('#skillMsg').textContent = '保存失败：' + e.message; }
      btn.disabled = false; btn.textContent = '保存规范';
    };
    return;
  }
  if (tab === 'feedback') { HOOKS.applications?.(); return; }
  HOOKS.strategyForm?.();
};

VIEWS.search = async () => {
  const [cfgHtml, jobsHtml, tgtHtml] = await Promise.all([renderSearchConfig(), renderJobPool(), renderSearchTargets()]);
  return `
  <div class="sectionhead"><span class="num">0</span>目标岗位 <span class="tag">最大前提：选中一个，技能分析 / 简历标题 / 匹配口径都跟随它，改动即时保存</span></div>
  ${tgtHtml}
  <div class="sectionhead"><span class="num">1</span>搜岗设置 <span class="tag">每轮开跑前在这里确认参数</span></div>
  ${cfgHtml}
  <div class="sectionhead"><span class="num">2</span>岗位池 <span class="tag">已采集的岗位与 JD，下面的筛选只影响本页展示</span></div>
  ${jobsHtml}`;
};

/* 搜岗页「目标岗位」区块：最大前提，改动即时持久化到 profile（targets/activeTarget/title） */
async function renderSearchTargets() {
  const p = await api('/profile');
  return `<div id="targetSection" class="card" style="margin-bottom:0">${targetsHtml(p, { open: false })}</div>`;
}

let __tgtTimer = null;
async function persistSearchTargets(immediate) {
  clearTimeout(__tgtTimer);
  const run = async () => {
    try {
      const p = await api('/profile');
      collectRowsFromDom(p);
      const saved = await api('/profile', { method: 'PUT', body: p });
      if (window.__jobPoolRefresh) window.__jobPoolRefresh(saved);   // 岗位池按新目标/新关键词联动
    } catch (e) { toast('目标岗位保存失败：' + (e.message || '').slice(0, 50), true); }
  };
  if (immediate) return run();
  __tgtTimer = setTimeout(run, 400);
}

async function rerenderTargetSection() {
  const sec = $('#targetSection');
  if (!sec) return;
  const p = await api('/profile');
  sec.innerHTML = targetsHtml(p, { open: true });
  bindSearchTargets();
}

function bindSearchTargets() {
  const addT = $('#addTarget');
  if (addT) addT.onclick = async () => {
    const p = await api('/profile');
    collectRowsFromDom(p);
    (p.targets = p.targets || []).push({ id: 't' + Date.now(), title: '', keywords: [], note: '' });
    try { const saved = await api('/profile', { method: 'PUT', body: p }); if (window.__jobPoolRefresh) window.__jobPoolRefresh(saved); toast('已添加目标'); } catch (e) { toast('保存失败：' + (e.message || '').slice(0, 40), true); }
    rerenderTargetSection();
  };
  $$('#targetList [data-tdel]').forEach((b) => (b.onclick = async () => {
    const p = await api('/profile');
    collectRowsFromDom(p);
    const id = b.dataset.tdel;
    p.targets = (p.targets || []).filter((t) => t.id !== id);
    if (p.activeTarget === id) p.activeTarget = ((p.targets[0] || {}).id) || null;
    const cur2 = p.targets.find((t) => t.id === p.activeTarget) || p.targets[0] || {};
    p.title = cur2.title || '';
    try { const saved = await api('/profile', { method: 'PUT', body: p }); if (window.__jobPoolRefresh) window.__jobPoolRefresh(saved); } catch (e) { toast('保存失败：' + (e.message || '').slice(0, 40), true); }
    rerenderTargetSection();
  }));
  $$('#targetList [data-tactive]').forEach((r) => (r.onchange = async () => {
    await persistSearchTargets(true);
    rerenderTargetSection();
  }));
  $$('#targetList [data-ttitle]').forEach((el) => (el.oninput = () => persistSearchTargets(false)));
  $$('#targetList [data-tkw]').forEach((el) => (el.oninput = () => persistSearchTargets(false)));
}

async function renderStrategyForm() {
  const [st, sc] = await Promise.all([api('/strategy'), api('/schedule')]);
  const cad = st.cadence || {};
  const win = (st.time_windows || [{}]);
  const wd = (n) => ['一', '二', '三', '四', '五', '六', '日'][n - 1];
  return `
  <div class="strategy-form">
      <div class="card"><h3>执行方式 <span class="tag">决定 Agent 何时、投多少</span></h3>
        <div class="grid g3">
          <div class="field"><label>启用自动投递</label>
            <select id="stEnabled"><option value="true" ${st.enabled ? 'selected' : ''}>启用</option><option value="false" ${!st.enabled ? 'selected' : ''}>暂停</option></select></div>
          <div class="field"><label>模式</label>
            <select id="stMode"><option value="batch" ${st.mode === 'batch' ? 'selected' : ''}>batch · 按批执行</option>
            <option value="schedule" ${st.mode === 'schedule' ? 'selected' : ''}>schedule · 按周期自动</option></select></div>
          <div class="field"><label>周期类型</label>
            <select id="stCadType">
              <option value="daily" ${cad.type === 'daily' ? 'selected' : ''}>每天固定时间</option>
              <option value="interval" ${cad.type === 'interval' ? 'selected' : ''}>每隔 N 小时</option>
              <option value="weekly" ${cad.type === 'weekly' ? 'selected' : ''}>每周指定日</option></select></div>
        </div>
        <div class="grid g3">
          <div class="field"><label>执行时间点（逗号分隔）</label>
            <input id="stTimes" value="${esc((cad.times || []).join(', '))}" placeholder="09:30, 14:00"></div>
          <div class="field"><label>间隔小时（interval 模式）</label>
            <input id="stInterval" type="number" min="0" value="${esc(cad.interval_hours || 0)}"></div>
          <div class="field"><label>工作日（ISO 1-7）</label>
            <div class="chips">${[1, 2, 3, 4, 5, 6, 7].map((n) => `<label class="chip ${(cad.weekdays || []).includes(n) ? 'ok' : ''}" style="cursor:pointer">
              <input type="checkbox" data-wd="${n}" ${(cad.weekdays || []).includes(n) ? 'checked' : ''} style="width:auto"> 周${wd(n)}</label>`).join('')}</div></div>
        </div>
        <div class="grid g3">
          <div class="field"><label>每次投递岗位数</label><input id="stBatch" type="number" min="1" value="${esc(st.batch_size)}"></div>
          <div class="field"><label>每日上限</label><input id="stDaily" type="number" min="1" value="${esc(st.daily_limit)}"></div>
          <div class="field"><label>允许时间段</label>
            <div class="row"><input id="stWinFrom" value="${esc((win[0] || {}).from || '')}" style="width:96px">
            <span class="muted">至</span><input id="stWinTo" value="${esc((win[0] || {}).to || '')}" style="width:96px"></div></div>
        </div>
      </div>
      <div class="card"><h3>风控与暂停条件</h3>
        <div class="grid g3">
          <div class="field"><label>投递前需我确认名单</label>
            <select id="stApproval"><option value="true" ${st.require_approval ? 'selected' : ''}>需要（更安全）</option>
            <option value="false" ${!st.require_approval ? 'selected' : ''}>不需要（全自动）</option></select></div>
          <div class="field"><label>连续无回复多少家后暂停</label><input id="stPause" type="number" min="1" value="${esc(st.pause_after_consecutive_no_reply)}"></div>
          <div class="field"><label>回复率低于多少时暂停</label><input id="stMinRate" type="number" step="0.01" min="0" value="${esc(st.min_reply_rate)}"></div>
        </div>
        <div class="grid g3">
          <div class="field"><label>同公司去重天数</label><input id="stDedupe" type="number" value="${esc(st.dedupe_days)}"></div>
          <div class="field"><label>同公司冷却天数</label><input id="stCooldown" type="number" value="${esc(st.per_company_cooldown_days)}"></div>
          <div class="field"><label>同公司最多投几次</label><input id="stMaxCo" type="number" value="${esc(st.max_per_company)}"></div>
        </div>
        <div class="chips">
          <label class="chip ${st.stop_on_risk_control ? 'ok' : ''}" style="cursor:pointer"><input type="checkbox" id="stRisk" ${st.stop_on_risk_control ? 'checked' : ''} style="width:auto"> 命中平台风控立即停止</label>
          <label class="chip ${(st.review_gate || {}).deterministic ? 'ok' : ''}" style="cursor:pointer"><input type="checkbox" id="stGateDet" ${(st.review_gate || {}).deterministic ? 'checked' : ''} style="width:auto"> 确定性简历校验</label>
          <label class="chip ${(st.review_gate || {}).independent_agent ? 'ok' : ''}" style="cursor:pointer"><input type="checkbox" id="stGateAgent" ${(st.review_gate || {}).independent_agent ? 'checked' : ''} style="width:auto"> 独立 Agent 复核</label>
        </div>
      </div>
      <div class="row" style="margin:2px 0 10px;align-items:center">
        <button class="primary" id="saveStrategy">保存</button>
        <button class="primary" id="runBatchNow">▶ 运行</button>
        <button id="reloadStrategy">重新载入</button>
      </div>
      <pre id="runBatchOut" class="small muted" style="white-space:pre-wrap;max-height:200px;overflow:auto;display:none;margin:0 0 14px;background:#f6f8fa;padding:8px;border-radius:6px;font-size:12px"></pre>
  </div>`;
};

async function renderJobPool() {
  const [jobs, cfg] = await Promise.all([api('/jobs'), api('/config')]);
  const cities = [...new Set(jobs.map((j) => j.city).filter(Boolean))];
  return `
  <div class="card"><h3>岗位池 <span class="tag">跟随顶部目标岗位 · 数据来自 BOSS 直聘</span>
      <span style="flex:1"></span>
      <button id="poolClear" class="sm warn" title="清空当前目标的岗位（重新采集前置）">清空当前目标岗位</button>
      <button id="poolPrune" class="sm" title="清洗岗位池：剔除校招/应届/实习岗 + 与当前目标不匹配的训练/算法向岗位（如「大模型应用开发专家」「LLM后训练」），规则见 job_filter.py，纯可复现，清洗前自动备份">🧹 清理错配岗位</button>
      <button id="poolRefresh" class="sm" title="去 BOSS 直聘按当前目标关键词拉取新岗位：先采集列表，再逐个进详情页回填薪资/JD，自动剔除与薪资区间不符的岗位">🔄 从 BOSS 拉取</button>
      <button id="poolActRefresh" class="sm" title="对活跃度为空的岗位重新访问详情页，抓取 HR 最新活跃状态">⚡ 刷新活跃度</button></h3>
    <div class="row" style="margin-bottom:10px">
      <span class="small muted" id="poolMatch"></span>
      <span class="small muted" id="poolFresh" style="margin-left:12px"></span>
      <span style="flex:1"></span>
      <select id="fSort" style="width:150px">
        <option value="match">排序：目标匹配优先</option>
        <option value="active">排序：招聘者活跃度</option>
        <option value="salary">排序：薪资从高到低</option>
        <option value="new">排序：最近采集</option>
      </select>
    </div>
    <div class="row" style="margin-bottom:10px">
      <select id="fType" style="width:118px"><option value="">全部类型</option><option>校招</option><option>社招</option></select>
      <select id="fCity" style="width:140px"><option value="">全部城市</option>${cities.map((c) => `<option>${esc(c)}</option>`).join('')}</select>
      <select id="fMatch" style="width:130px">
        <option value="">相关度（岗位×履历匹配度）：全部</option>
        <option value="strong">≥60% 高匹配</option>
        <option value="weak">35–59% 中匹配</option>
        <option value="none">低匹配 / 未评估</option>
      </select>
      <select id="fActive" style="width:170px">
        <option value="cfg" selected>按搜岗参数（${(cfg.activity_preference || []).join('/') || '未设置'}）</option>
        <option value="">活跃度：全部</option>
        <option>刚刚活跃</option><option>今日活跃</option><option>3日内活跃</option>
        <option>本周活跃</option><option>本月活跃</option><option>更早</option>
      </select>
      <input id="fKw" placeholder="搜索公司 / 岗位 / JD" style="flex:1;min-width:200px">
      <span class="small muted" id="fCount" style="margin-left:8px"></span>
    </div>
    <div class="tablewrap"><table><thead><tr>
      <th>公司</th><th>岗位</th><th>城市</th><th>薪资</th><th>经验</th><th>类型</th><th>相关度</th><th>技能标签</th><th>活跃度</th>
    </tr></thead><tbody id="jobBody"></tbody></table></div>
    <div class="row" id="pager" style="margin-top:10px;justify-content:center;gap:6px"></div>
  </div>`;
};

/* 岗位洞察/差距按洞察目标口径：面板内自选（localStorage 记忆，优先），未选则跟随搜岗当前目标 */
async function ensureTargetTree() {
  const t = await api('/skills');
  let p = null, want = null;
  try { p = await api('/profile'); } catch (e) { /* 读不到 profile 时按现有数据展示 */ }
  const ins = localStorage.getItem('insightTarget');
  want = ins || (p && (p.activeTarget || ((p.targets || [])[0] || {}).id)) || null;
  if (want && t.target && t.target.id !== want) {
    toast('洞察目标，按「' + ((t.target && t.target.title) || '新目标') + '」重算…');
    const q = ins ? '?target=' + encodeURIComponent(ins) : '';
    const r = await api('/analyze' + q, { method: 'POST', body: {} });
    if (r.ok) return await api('/skills');
    toast('重新分析失败：' + (r.stderr || r.error || '').slice(0, 80), true);
  }
  return t;
}

/* 洞察目标切换栏（面板内自选，localStorage 记忆；空 = 跟随搜岗当前目标） */
function insightTargetBar(prof, tgt) {
  const targets = (prof && prof.targets) || [];
  if (!targets.length) return tgt.title ? `<div class="small" style="margin-bottom:8px">当前目标：<b>${esc(tgt.title)}</b></div>` : '';
  const act = (targets.find((x) => String(x.id) === String(prof && prof.activeTarget))) || {};
  const insNow = localStorage.getItem('insightTarget');
  const opts = [`<option value="" ${insNow ? '' : 'selected'}>跟随搜岗（${esc(act.title || '当前目标')}）</option>`]
    .concat(targets.map((x) => `<option value="${esc(x.id)}" ${insNow && String(x.id) === String(tgt.id) ? 'selected' : ''}>${esc(x.title)}</option>`));
  return `<div class="row" style="margin-bottom:10px;gap:8px;padding:7px 10px;background:#f4f6fa;border:1px solid var(--line);border-radius:8px"><span class="small"><b>洞察目标</b></span>
    <select id="insightTarget" style="width:auto;min-width:200px" onchange="switchInsight(this.value, this.options[this.selectedIndex].text)">${opts.join('')}</select>
    <span class="small muted">面板内独立切换并重算，不依赖搜岗的当前目标（选「跟随搜岗」除外）</span></div>`;
}

VIEWS.skills = async () => {
  const t = await ensureTargetTree();
  const g = await api('/gap').catch(() => null);
  const c = t.corpus || {};
  const docN = c.documented || ((c.withJd || 0) + (c.withTags || 0)) || c.jobs || 0;
  const tgt = t.target || {};
  const prof = await api('/profile').catch(() => null);
  const tgtLine = insightTargetBar(prof, tgt);
  const kpi = (k, v, d, cls) => `<div class="kpi"><div class="k">${k}</div><div class="v ${cls || ''}">${v}</div><div class="d">${d}</div></div>`;
  const isNew = !!(g && g.engine === 'jd_match_v1');
  if (!t.domains || !t.domains.length) return `
    <div class="tabs"><a class="on" href="#/skills">岗位洞察</a></div>
    ${tgtLine}
    <div class="card"><h3>岗位洞察</h3><div class="empty">岗位洞察尚未生成，点下面按钮重新分析。</div>
      <div class="row" style="margin-top:10px"><button class="primary" id="btnAnalyze">重新分析岗位洞察</button></div></div>`;
  const st = insightStats(t);
  const mr = (g && g.matchRate) || null;
  const top3 = ((g && g.gaps) || []).slice(0, 3).map((x) => {
    const chip = gtChip(x.gapType);
    return `<span class="chip ${chip.c}">${chip.t} · ${esc(x.dim)}</span>`;
  }).join('');
  const oldRows = ((g && g.strengths) || []).map((s) => `<tr><td>${esc(s.skill)}</td><td class="mono">${s.myScore ?? 0} 分 · ${esc(s.myTier || '')}</td>
    <td class="mono">${Math.round((s.coverage || 0) * 100)}%</td><td class="small muted">${esc(s.note || '')}</td></tr>`).join('');
  return `
  <div class="tabs"><a class="on" href="#/skills">岗位洞察</a>
    <span class="small muted" style="margin-left:auto">证据明细在「搜岗 → 点岗位 → 匹配分析」</span>
    <button class="primary sm" id="btnAnalyze" style="margin-left:10px" title="岗位池或履历变化后重算">重新分析</button></div>
  ${tgtLine}
  ${isNew ? renderHardBanner(g) : ''}
  <div class="grid g4">
    ${kpi('岗位池', c.jobs || 0, '已采集岗位')}
    ${kpi('参与统计语料', docN, '有技能标签或完整 JD')}
    ${kpi('需求维度', (mr && mr.total) || st.hotSkills.length, isNew ? 'JD 解析出的能力需求向量' : '高频技能点（旧口径）')}
    ${kpi('层级匹配率', (mr && mr.overall + '%') || st.matchRate + '%', isNew ? (mr.matched + '/' + mr.total + ' 维度达标') : (st.haveRate + '% 技能已具备（旧口径）'), mr && mr.overall < 35 ? 'warn' : '')}
  </div>
  ${isNew ? renderVerbProfile(g) : ''}
  ${isNew ? renderMatchDual(g) : renderMatchInsight(st)}
  ${isNew ? renderDims(g, tgt.id) : renderMissing(g)}
  ${isNew ? renderIgnored(g, tgt.id) : ''}
  ${isNew ? renderCards(g) : ''}
  ${renderHotSkills(st, docN)}
  ${isNew ? renderStrengths(g) : (oldRows ? `<div class="card"><h3>已有优势 <span class="tag">可写进简历与面试话术</span></h3>
    <div class="tablewrap"><table><thead><tr><th>技能</th><th>水平</th><th>需求度</th><th>说明</th></tr></thead><tbody>${oldRows}</tbody></table></div></div>` : '')}
  ${g && g.gaps && g.gaps.length && !isNew ? `<div class="card"><h3>总体结论 <span class="tag">生成于 ${esc(g.generatedAt || '')}</span></h3>
    <div>${esc(g.summary || '')}</div>
    <div class="chips" style="margin-top:10px"><b class="small">Top 缺口：</b>${top3}</div>
    ${(g.recommendations || []).length ? `<div class="hr"></div><b class="small">行动建议</b><ul class="small">${g.recommendations.map((r) => `<li>${esc(r)}</li>`).join('')}</ul></div>` : ''}</div>` : ''}
  ${renderInsightOps(t, c, docN, isNew)}`;
};

/* 洞察面板内按目标切换（localStorage 记忆，独立于搜岗的当前目标；空 id = 跟随搜岗） */
window.switchInsight = async (id, title) => {
  if (id) { localStorage.setItem('insightTarget', id); toast('按「' + (title || id) + '」重算岗位洞察…'); }
  else { localStorage.removeItem('insightTarget'); toast('跟随搜岗当前目标重算…'); }
  try {
    const r = await api('/analyze' + (id ? '?target=' + encodeURIComponent(id) : ''), { method: 'POST', body: {} });
    if (!r.ok) throw new Error(r.stderr || '分析失败');
    toast('已按新目标更新');
    await route();
  } catch (e) {
    toast('重算失败：' + (e.message || '').slice(0, 60), true);
  }
};

/* 优先级火焰图热力色（1-5：蓝 → 青 → 黄 → 橙 → 红） */
function heatChip(p, lv) {
  const n = Number(p) || 0;
  const level = lv || (n >= 1.6 ? 1 : n >= 1.4 ? 2 : 3);   // 旧数据兜底映射
  const txt = { 1: 'L1 必须处理', 2: 'L2 最好处理', 3: 'L3 可处理可不处理' }[level] || 'L3 可处理';
  return `<span class="chip heatL${level}"><b>${txt}</b></span>`;
}
/* 缺口等级（1 必须 / 2 最好 / 3 可处理）；旧数据按 priority 兜底 */
const levelOf = (x) => Number(x.priorityLevel) || (Number(x.priority) >= 1.6 ? 1 : Number(x.priority) >= 1.4 ? 2 : 3);

/* 岗位洞察统计：匹配度指标（覆盖率加权，口径可复现） */
function insightStats(t) {
  const skills = [];
  (t.domains || []).forEach((d) => ((d.skills) || []).forEach((s) => skills.push(Object.assign({ domain: d.name }, s))));
  const have = (s) => (s.myScore || 0) >= 60;
  const maxCov = skills.reduce((a, s) => Math.max(a, s.coverage || 0), 0);
  const hot = Math.max(0.10, Math.round(maxCov * 0.5 * 1000) / 1000);          // 热门线：最高覆盖率的一半（下限 10%）
  const totalCov = skills.reduce((a, s) => a + (s.coverage || 0), 0);
  const haveCov = skills.reduce((a, s) => a + (have(s) ? (s.coverage || 0) : 0), 0);
  const hotSkills = skills.filter((s) => (s.coverage || 0) >= hot);
  const hotHave = hotSkills.filter(have).length;
  const sorted = [...skills].sort((a, b) => ((b.coverage || 0) - (a.coverage || 0)) || ((b.mentions || 0) - (a.mentions || 0)));
  return {
    skills, hot, hotSkills, hotHave, sorted,
    matchRate: totalCov ? Math.round((haveCov / totalCov) * 100) : 0,           // 需求覆盖率加权匹配度
    haveRate: skills.length ? Math.round((skills.filter(have).length / skills.length) * 100) : 0,
    hotHitRate: hotSkills.length ? Math.round((hotHave / hotSkills.length) * 100) : 0,
  };
}

/* 高频技能点：跨领域按覆盖率排序，标注命中数与我的状态 */
function renderHotSkills(st, docN) {
  const rows = st.sorted.filter((s) => (s.coverage || 0) >= st.hot).slice(0, 20).map((s) => {
    const tier = s.coverageTier || '';
    const chip = tier === '必备' ? 'bad' : tier === '常见' ? 'on' : 'mute';
    const state = s.inProfile
      ? `<span class="chip ok">我有 ${s.myScore || 0} 分</span>`
      : `<span class="chip ${s.gap ? 'bad' : 'mute'}">${s.gap ? '缺失' : '无证据'}</span>`;
    return `<div class="skillrow" style="grid-template-columns:210px 1fr 120px 92px">
      <div class="nm">${esc(s.name)}<span class="chip slim mute">${esc(s.domain || '')}</span></div>
      <div class="row" style="gap:8px"><div class="bar" style="flex:1"><i style="width:${Math.round(s.coverage * 100)}%"></i></div>
        <span class="mono small">${s.mentions}/${docN}</span></div>
      <span class="chip ${chip}">${esc(tier || '-')}</span>
      ${state}</div>`;
  }).join('');
  return `<div class="card"><h3>高频技能点 <span class="tag">热门线以上 ${st.hotSkills.length} 个 · 按需求覆盖率排序</span></h3>
    ${rows || '<div class="empty">岗位池样本不足，暂无明显高频技能</div>'}</div>`;
}

/* 技术栈构成：按领域聚合 */
function renderDomainMix(t) {
  const rows = (t.domains || []).map((d) => {
    const skills = d.skills || [];
    const maxCov = skills.reduce((a, s) => Math.max(a, s.coverage || 0), 0);
    const gapN = skills.filter((s) => (s.myScore || 0) < 60).length;
    return `<div class="skillrow" style="grid-template-columns:170px 1fr 200px">
      <div class="nm"><b>${esc(d.name)}</b></div>
      <div class="bar" style="flex:1"><i style="width:${Math.round(maxCov * 100)}%"></i></div>
      <div class="small muted">${skills.length} 个技能 · 领域最高 ${Math.round(maxCov * 100)}% · 缺口 ${gapN}</div>
    </div>`;
  }).join('');
  return `<div class="card"><h3>技术栈构成 <span class="tag">按领域聚合 · 条为领域内最高覆盖率</span></h3>${rows}</div>`;
}

/* 匹配度分析：需求覆盖率加权 + 具备率 + 高频命中率 */
function renderMatchInsight(st) {
  const pct = st.matchRate;
  const verdict = pct >= 70 ? '匹配度较高' : pct >= 45 ? '匹配度一般' : '匹配度偏低';
  const verdictCls = pct >= 70 ? 'ok' : pct >= 45 ? 'on' : 'bad';
  const note = pct >= 70
    ? '岗位技术栈的大部分你已经具备，重点是把已有优势写成可验证、可量化的成果。'
    : pct >= 45
      ? '岗位技术栈覆盖过半，剩余缺口集中在下方「缺失技能清单」，优先补高频且零基础的项。'
      : '岗位技术栈与履历重合度偏低，建议先对照「缺失技能清单」补齐高频项，再调整简历措辞。';
  const box = (k, v, d) => `<div class="kpi"><div class="k">${k}</div><div class="v">${v}</div><div class="d">${d}</div></div>`;
  return `<div class="card"><h3>匹配度分析 <span class="tag">覆盖率加权 · 口径可复现</span></h3>
    <div class="row" style="gap:22px;flex-wrap:wrap">
      <div class="ring" style="--p:${pct}%"><div style="position:relative;z-index:1;text-align:center"><b>${pct}%</b><div class="small muted">需求覆盖率</div></div></div>
      <div class="grid g3" style="flex:1;min-width:300px">
        ${box('技能具备率', st.haveRate + '%', '证据分 ≥ 60 的技能占比')}
        ${box('高频技能命中', st.hotHitRate + '%', '热门线以上技能中已具备的比例')}
        ${box('高频缺口', st.hotSkills.length - st.hotHave, '热门线以上但尚未具备')}
      </div>
    </div>
    <div class="row" style="margin-top:12px"><span class="chip ${verdictCls}"><b>${verdict}</b></span>
      <span class="small muted">${esc(note)}</span></div>
    <div class="small muted" style="margin-top:8px">匹配度 = 已具备技能的覆盖率之和 ÷ 全部技能的覆盖率之和。覆盖率越高代表越多岗位要求它，按覆盖率加权更贴近「岗位真正要什么」。</div>
  </div>`;
}

/* ================= 层级语义匹配（jd_match_v1）渲染 ================= */
/* 六色差距分型 meta */
function gtChip(t) {
  const m = {
    hard: { c: 'gt-hard', t: '⛔ 硬差距' },
    structure: { c: 'gt-structure', t: '🏗️ 结构差距' },
    wording: { c: 'gt-wording', t: '✏️ 表述差距' },
    migrate: { c: 'gt-migrate', t: '🔁 迁移差距' },
    learn: { c: 'gt-learn', t: '📚 学习差距' },
    ok: { c: 'gt-ok', t: '✅ 达标' },
    over: { c: 'gt-over', t: '🌟 超配' },
  };
  return m[t] || { c: 'mute', t: (t || '') };
}
const GT_META = {
  hard: { t: '⛔ 硬差距', d: 'must 且履历完全无痕迹、无地基：投递硬门槛' },
  structure: { t: '🏗️ 结构差距', d: 'must 缺失但有同领域地基，建议补项目' },
  wording: { t: '✏️ 表述差距', d: '有近义经验但没按 JD 措辞表达，改写即可' },
  migrate: { t: '🔁 迁移差距', d: '邻接维度可迁移表述 + 补一个落地案例' },
  learn: { t: '📚 学习差距', d: '加分项完全缺失，列入学习计划' },
  ok: { t: '✅ 达标', d: '已满足层级要求，按岗位措辞对齐' },
  over: { t: '🌟 超配', d: '比要求高一级：差异化武器，面试主引导方向' },
};
/* 硬差距警示（报告顶部直接给结论，不藏着掖着） */
function renderHardBanner(g) {
  const h = (g && g.hardGaps) || [];
  if (!h.length) return '';
  return `<div class="hardbanner"><b>⚠️ 投递警示</b> 该岗位族存在 ${h.length} 个硬差距维度：${h.map((x) => `${esc(x.dim)}（要求 ${esc(x.required)}）`).join('、')}。命中这些维度的岗位建议谨慎投递——先补一个真实项目，或把简历重心移到能扬长避短的岗位。</div>`;
}
/* 岗位职责动词画像：JD 语料里要求什么层级的人 */
function renderVerbProfile(g) {
  const vp = (g && g.position && g.position.verbProfile) || null;
  if (!vp) return '';
  const total = Object.values(vp).reduce((a, b) => a + (Number(b) || 0), 0) || 1;
  const bars = Object.entries(vp).map(([k, v]) =>
    `<div class="vrow"><span class="vlabel">${k}</span><div class="bar" style="flex:1"><i style="width:${Math.round((Number(v) || 0) / total * 100)}%"></i></div><span class="mono small">${v} 岗</span></div>`).join('');
  return `<div class="card"><h3>岗位职责动词画像 <span class="tag">JD 语料中职责动词频次 · 治理&gt;主导&gt;负责&gt;参与</span></h3>${bars}</div>`;
}
/* 匹配率双轴：层级匹配率 + 证据质量 */
function renderMatchDual(g) {
  const mr = (g && g.matchRate) || { overall: 0, evidenceQuality: 0, matched: 0, total: 0, hard: 0 };
  const pct = mr.overall || 0;
  const verdict = pct >= 60 ? '匹配度较高' : pct >= 35 ? '匹配度一般' : '匹配度偏低';
  const verdictCls = pct >= 60 ? 'ok' : pct >= 35 ? 'on' : 'bad';
  const note = pct >= 60
    ? '大部分需求维度已达标，重点是强化超配武器与补证据口径。'
    : pct >= 35
      ? '约半数维度达标，剩余差距集中在下方「需求维度 × 层级差距」，先做表述/迁移差距（改写即回收），再补学习差距。'
      : '达标维度少，优先处理硬差距与表述差距：硬差距决定岗位能不能投，表述差距决定简历改完能回收多少。';
  const box = (k, v, d) => `<div class="kpi"><div class="k">${k}</div><div class="v">${v}</div><div class="d">${d}</div></div>`;
  return `<div class="card"><h3>匹配率双轴 <span class="tag">层级匹配率 + 证据质量分开看，不合并成单分</span></h3>
    <div class="row" style="gap:22px;flex-wrap:wrap">
      <div class="ring" style="--p:${pct}%"><div style="position:relative;z-index:1;text-align:center"><b>${pct}%</b><div class="small muted">层级匹配率</div></div></div>
      <div class="grid g3" style="flex:1;min-width:300px">
        ${box('证据质量', (mr.evidenceQuality || 0) + '%', '命中维度中带量化口径（业务/技术指标）的占比')}
        ${box('达标维度', mr.matched + '/' + mr.total, '层级达到岗位要求 minLevel 的维度数')}
        ${box('硬差距', mr.hard || 0, 'must 且完全无痕迹，决定可投性')}
      </div>
    </div>
    <div class="row" style="margin-top:12px"><span class="chip ${verdictCls}"><b>${verdict}</b></span>
      <span class="small muted">${esc(note)}</span></div>
    <div class="small muted" style="margin-top:8px">匹配率 = Σ(min(实际层级, 要求层级) × 权重) ÷ Σ(要求层级 × 权重)，超配不计分（防止改写刷分），超配维度单独进「已有优势」作为差异化武器。</div>
  </div>`;
}
/* 需求维度 × 层级差距（六色分型） */
function renderDims(g, targetId, showOps = true) {
  const dims = (g && g.dims) || [];
  if (!dims.length) return '';
  const tid = targetId || 'global';
  const cards = (g && g.cards) || {};
  // 把行动卡按 dim 建索引
  const actionByDim = {};
  (cards.resume || []).forEach((c) => { actionByDim[c.dim] = { kind: '✏️ 简历改写', action: c.action, required: c.required }; });
  (cards.evidence || []).forEach((c) => { actionByDim[c.dim] = { kind: '📐 证据补全', action: c.action, required: c.required }; });
  (cards.learn || []).forEach((c) => { actionByDim[c.dim] = { kind: '📚 学习', action: c.focus, steps: c.steps, resources: c.resources, duration: c.duration }; });

  // 按 gapType/category 分三级
  const levelOf = (d) => {
    if (d.gapType === 'hard' || d.gapType === 'structure') return 1;
    if (d.category === 'must' && (d.gapType === 'wording' || d.gapType === 'migrate' || d.gapType === 'learn')) return 2;
    return 3;
  };
  const groups = [
    { level: 1, title: '必须弥补', color: '#c0392b', desc: '硬差距/结构差距 —— 投递硬门槛' },
    { level: 2, title: '最好弥补', color: '#d68910', desc: 'must 但有基础 —— 改写简历即可回收' },
    { level: 3, title: '可选弥补', color: '#2e7d32', desc: '加分项 —— 有余力再补' },
  ];
  groups.forEach((gr) => { gr.items = dims.filter((d) => levelOf(d) === gr.level); });

  const renderDimCard = (d) => {
    const chip = gtChip(d.gapType);
    const jdEvs = d.jdEvidence || [];
    const myEvs = d.myEvidence || [];
    const act = actionByDim[d.dim];
    const hasDetail = jdEvs.length || myEvs.length || (act && (act.steps || act.resources));
    return `<details class="dimcard" open style="border:1px solid #e5e7eb;border-radius:8px;margin:6px 0;background:#fff">
      <summary style="padding:8px 12px;cursor:pointer;display:flex;align-items:center;gap:10px;list-style:none">
        <div style="flex:1;min-width:0">
          <b>${esc(d.dim)}</b>
          <span class="chip slim mute">${esc(d.domain || '')}</span>
          <span class="chip ${d.category === 'must' ? 'bad' : 'mute'} slim">${d.category === 'must' ? 'must' : '加分'}</span>
          <span class="chip ${chip.c} slim">${chip.t}</span>
        </div>
        <div class="small muted" style="white-space:nowrap">要求 <b>${esc(d.required)}</b> · 实际 ${d.actual === 'L0' ? '—' : '<b>' + esc(d.actual) + '</b>'}</div>
        ${hasDetail ? '<span class="small muted" style="font-size:11px">展开证据 ▾</span>' : ''}
      </summary>
      <div style="padding:8px 12px;border-top:1px dashed #e5e7eb">
        <div class="small" style="margin-bottom:6px"><b>建议：</b>${esc(d.leverage || '')}</div>
        ${act ? `<div class="small" style="margin:4px 0;padding:6px 8px;background:#f4f6fa;border-radius:6px">
          <b>${esc(act.kind)}</b>${act.duration ? ` <span class="chip mute slim">${esc(act.duration)}</span>` : ''}
          <div style="margin-top:2px">${esc(act.action || '')}</div>
          ${(act.steps || []).length ? `<ol class="small" style="margin:4px 0 0 18px;padding:0">${act.steps.map((s) => `<li>${esc(s)}</li>`).join('')}</ol>` : ''}
          ${(act.resources || []).length ? `<div class="row" style="margin-top:4px;flex-wrap:wrap;gap:6px">${act.resources.map((r) => r.url ? `<a class="chip link" href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.type || '资料')}：${esc(r.name)} ↗</a>` : `<span class="chip">${esc(r.type || '资料')}：${esc(r.name)}</span>`).join('')}</div>` : ''}
        </div>` : ''}
        ${jdEvs.length ? `<div class="small muted quote" style="margin-top:6px"><b>JD 引用（${jdEvs.length} 条）：</b>${jdEvs.map(e => `<div>· ${esc((e.text||'').slice(0,120))}</div>`).join('')}</div>` : ''}
        ${myEvs.length ? `<div class="small" style="margin-top:6px;color:#1f7a3d"><b>履历证据（${myEvs.length} 条）：</b>${myEvs.map(e => `<div>· ${esc(e.source)}：${esc(e.text)}</div>`).join('')}</div>` : ''}
        <div class="small muted" style="margin-top:6px;display:flex;justify-content:space-between;align-items:center">
          <span>权重 ${d.weight} · 命中 ${d.mentions} 岗 · 职责动词「${esc(d.respVerb || '-')}」</span>
          ${showOps ? `<button class="linkish" data-ignore-dim="${esc(d.dim)}" data-target="${esc(tid)}">忽略此维度</button>` : ''}
        </div>
      </div>
    </details>`;
  };

  return `<div class="card"><h3>需求维度 × 层级差距 <span class="tag">按优先级三级分组 · 点卡片展开 JD/履历证据</span></h3>
    <div class="small muted" style="padding:8px 10px;background:#f4f6fa;border-radius:6px;margin-bottom:8px;line-height:1.7">
      <b>层级定义：</b>
      <b>L1 用会</b>——用过/了解，能跟着做；
      <b>L2 负责实现</b>——独立负责模块落地，写代码/做方案；
      <b>L3 主导设计</b>——主导架构/体系设计，从 0 到 1 搭建；
      <b>L4 治理闭环</b>——制定标准/规范/机制，跨团队推广，对结果负责。
      <br><b>六色分型：</b>✅达标 · 🌟超配 · ✏️表述（有经验但措辞不对）· 🔁迁移（邻接维度可迁移）· 📚学习（加分项缺失）· 🏗️结构（有地基缺项目）· ⛔硬（must 且零痕迹）。
    </div>
    ${groups.map((gr) => gr.items.length ? `
      <details open style="margin:12px 0 4px;border:1px solid ${gr.color}40;border-radius:8px;overflow:hidden">
        <summary style="padding:8px 12px;cursor:pointer;font-weight:700;color:${gr.color};font-size:13px;background:${gr.color}10;list-style:none">
          ${gr.title} <span class="small" style="font-weight:400;color:#666">· ${gr.desc} · ${gr.items.length} 个缺项</span>
        </summary>
        <div style="padding:6px 4px">
        ${gr.items.map(renderDimCard).join('')}
        </div>
      </details>` : '').join('')}
  </div>`;
}
/* 已忽略维度（用户校准，可恢复） */
function renderIgnored(g, targetId) {
  const ig = (g && g.ignoredDims) || [];
  if (!ig.length) return '';
  const tid = targetId || 'global';
  const rows = ig.map((r) => `<div class="dimrow ignored">
    <div class="nm"><b>${esc(r.dim)}</b><span class="chip slim mute">${esc(r.domain || '')}</span></div>
    <div class="lv"><span class="small muted">要求</span> <b>${esc(r.required)}</b></div>
    <div class="lv"><span class="small muted">类别</span> <b>${r.category === 'must' ? 'must' : '加分'}</b></div>
    <div class="act small muted">已从需求向量剔除，不计入匹配率。${(r.jdEvidence || [])[0] ? `<span class="quote">JD 原文：${esc((r.jdEvidence || [])[0].text || '').slice(0, 70)}</span>` : ''}</div>
    <div class="ops"><button class="linkish" data-restore-dim="${esc(r.dim)}" data-target="${esc(tid)}">恢复</button></div></div>`).join('');
  return `<div class="card ignored-card"><h3>已忽略维度 <span class="tag">用户校准 · 判定为与目标岗位无关 · 共 ${ig.length} 维</span></h3>${rows}</div>`;
}
/* 四张行动卡 → 已合并进 renderDims 三级分组，这里只保留面试预演卡 */
function renderCards(g) {
  const cards = (g && g.cards) || {};
  if (!cards.interview || !cards.interview.length) return '';
  return `<div class="card"><h3>🎤 面试预演卡 <span class="tag">超配/低置信/无量化的交叉项会被深挖 · ${cards.interview.length} 项</span></h3>
    ${cards.interview.map((c) => `<div class="actitem"><b>${esc(c.dim)}</b><span class="chip mute slim">实际 ${esc(c.actual || 'L0')}</span>
      <div class="small muted">${esc(c.why || '')}</div><div class="small">${esc(c.prepare || '')}</div></div>`).join('')}
  </div>`;
}
/* 已有优势：达标/超配维度 = 简历前置 + 面试主打 */
function renderStrengths(g) {
  const st = ((g && g.strengths) || []).filter((s) => s.gapType === 'ok' || s.gapType === 'over');
  if (!st.length) return '';
  return `<div class="card"><h3>已有优势 <span class="tag">达标/超配维度 · 简历前置 + 面试主引导方向</span></h3>
    <div class="tablewrap"><table><thead><tr><th>维度</th><th>层级</th><th>类别</th><th>打法</th></tr></thead><tbody>
    ${st.map((s) => `<tr><td><b>${esc(s.dim)}</b></td><td class="mono">要求 ${esc(s.required)} · 实际 ${esc(s.actual)}</td>
      <td>${s.gapType === 'over' ? '<span class="chip gt-over">超配</span>' : '<span class="chip gt-ok">达标</span>'}</td>
      <td class="small muted">${esc(s.leverage || '')}</td></tr>`).join('')}
    </tbody></table></div></div>`;
}

/* 用户校准：忽略/恢复需求维度 → 保存 → 重算 → 重渲染 */
window.toggleIgnoreDim = async (dim, action, targetId) => {
  const tid = targetId || 'global';
  const cur = await api('/insight/ignore').catch(() => null);
  const targets = (cur && cur.targets) || {};
  const list = (targets[tid] || []).slice();
  if (action === 'ignore') {
    if (list.indexOf(dim) < 0) list.push(dim);
  } else {
    const i = list.indexOf(dim);
    if (i >= 0) list.splice(i, 1);
  }
  const r = await api('/insight/ignore', { method: 'PUT', body: { target: tid, dims: list } }).catch((e) => ({ ok: false, error: e.message }));
  if (!r.ok) { toast('保存忽略列表失败：' + (r.error || '').slice(0, 60), true); return; }
  toast(action === 'ignore' ? `已忽略「${dim}」，重算匹配率…` : `已恢复「${dim}」，重算匹配率…`);
  try {
    const rr = await api('/analyze' + (tid !== 'global' ? '?target=' + encodeURIComponent(tid) : ''), { method: 'POST', body: {} });
    if (!rr.ok) throw new Error(rr.stderr || '分析失败');
    toast('匹配分析已更新');
    await route();
  } catch (e) {
    toast('重算失败：' + (e.message || '').slice(0, 60), true);
  }
};

/* 全局委托：维度忽略/恢复按钮（内容为动态渲染，必须在渲染后按 data-* 委托） */
document.addEventListener('click', (e) => {
  const ig = e.target.closest('[data-ignore-dim]');
  if (ig) { e.preventDefault(); toggleIgnoreDim(ig.dataset.ignoreDim, 'ignore', ig.dataset.target); return; }
  const rs = e.target.closest('[data-restore-dim]');
  if (rs) { e.preventDefault(); toggleIgnoreDim(rs.dataset.restoreDim, 'restore', rs.dataset.target); }
});

/* 缺失技能清单：按 L1/L2/L3 分组折叠，卡片内含完整学习方案 */
function renderMissing(g) {
  if (!g || !g.gaps || !g.gaps.length) return `<div class="card"><h3>缺失技能清单 <span class="tag">按优先级分 3 档</span></h3><div class="empty">没有明显缺口，匹配度较好</div></div>`;
  const linkify = (s) => esc(s).replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>');
  const resChip = (r) => r && r.url
    ? `<a class="chip link" href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.type || '资料')}：${esc(r.name)} ↗</a>`
    : `<span class="chip">${esc(r.type || '资料')}：${esc(r.name)}</span>`;
  const card = (x) => {
    const lv = levelOf(x);
    const pl = x.plan || {};
    return `<div class="gapcard lv${lv}">
      <h4><span>${esc(x.skill)} <span class="chip mute small">${esc(x.domain || '')}</span></span>
        ${heatChip(x.priority, lv)}</h4>
      <div class="kv">
        <div class="k">需求度</div><div>${Math.round((x.coverage || 0) * 100)}% · ${x.mentions || 0} 个岗位提到 · ${esc(x.coverageTier || '-')}</div>
        <div class="k">我的证据分</div><div>${x.myScore ?? 0} 分 · ${esc(x.myTier || '无证据')}</div>
        <div class="k">为什么</div><div>${esc(x.why || '')}</div>
        <div class="k">学习重点</div><div>${esc(pl.focus || '')}</div>
        <div class="k">预计周期</div><div>${esc(pl.duration || '')}</div>
        <div class="k">验证方式</div><div>${esc(pl.verification || '')}</div>
        ${(x.relatedJobs || []).length ? `<div class="k">相关岗位</div><div class="small">${x.relatedJobs.slice(0, 3).map(esc).join('、')}</div>` : ''}
      </div>
      ${(pl.steps || []).length ? `<div class="hr"></div><b class="small">学习步骤</b><ol class="small">${pl.steps.map((s) => `<li>${linkify(s)}</li>`).join('')}</ol>` : ''}
      ${(pl.resources || []).length ? `<div class="row" style="margin-top:8px;flex-wrap:wrap;gap:6px">${pl.resources.map(resChip).join('')}</div>` : ''}
    </div>`;
  };
  const groups = [1, 2, 3].map((lv) => {
    const items = (g.gaps || []).filter((x) => levelOf(x) === lv);
    if (!items.length) return '';
    const lab = { 1: 'L1 · 必须处理', 2: 'L2 · 最好处理', 3: 'L3 · 可处理可不处理' }[lv];
    return `<details class="gapgroup" ${lv === 1 ? 'open' : ''}><summary><b>${lab}</b>
      <span class="chip mute small">${items.length} 项</span><span class="fold">${lv === 1 ? '点击收起' : '点击展开'}</span></summary>
      ${items.map(card).join('')}</details>`;
  }).join('');
  return `<div class="card"><h3>缺失技能清单 <span class="tag">按优先级分 3 档 · 每档可折叠 · 卡片内含完整学习方案</span></h3>${groups || '<div class="empty">没有明显缺口，匹配度较好</div>'}</div>`;
}

/* 口径说明卡片（重新分析按钮已挪到右上角 tabs 行） */
function renderInsightOps(t, c, docN, isNew) {
  isNew = !!isNew;
  return `<div class="card"><h3>口径 <span class="tag">岗位 ${c.jobs || 0} 条 · 有技能标签或 JD 的 ${docN} 条 · ${isNew ? '层级语义匹配 v1' : '旧覆盖率口径'} · 生成于 ${esc(t.generatedAt || '')}</span></h3>
    ${isNew ? `
    <div class="small muted">层级语义匹配（v1）：JD 语料 → 能力需求向量（维度 × 最低层级 L1-L4 × 权重 × must/加分），
      L1 用会 / L2 负责实现 / L3 主导设计 / L4 治理闭环。履历侧按证据锚点做同一定义判定（statement 动词 + 落点 + 量化口径），
      引用做子串校验闭环。六色差距分型 = 达标 / 超配 / 表述（近义经验未按 JD 措辞表达）/ 迁移（邻接维度）/ 学习（加分项缺失）/
      结构（有地基缺项目）/ 硬（must 且零痕迹）。匹配率 = Σ(min(实际, 要求) × 权重) ÷ Σ(要求 × 权重)，超配不计分。
      覆盖率（高频技能点）仍为岗位池统计口径：提到该技能的岗位数 ÷ ${docN}。</div>
    <div class="small muted" style="margin-top:6px">设计依据：《履历 × 目标岗位匹配评估系统 — 设计方案 v1.0》——诊断价值 &gt; 分数价值，六色分型决定补救动作，硬差距直接提示谨慎投递，只产出改写/证据/学习建议，永不生成经历。</div>` : `
    <div class="small muted">覆盖率 = <b>提到该技能的岗位数 ÷ ${docN}</b>（只在有技能标签或完整 JD 的岗位里统计，避免被只有标题的岗位稀释）。
      分档由覆盖率推导：≥40% 必备 · ≥20% 常见 · ≥8% 加分 · 其余少见。<b>不使用人工指定的重要度</b>。
      热门线 = 最高覆盖率的一半（下限 10%）。匹配度与缺口均为同一份统计的可复现结论。</div>`}</div>`;
}

/* 差距与学习已并入「岗位洞察」单页（#/skills），旧 #/skills/gap 链接由 route 重定向 */

async function renderApplications() {
  const apps = await api('/applications');
  const STATUSES = ['未沟通', '已沟通', '简历已发', '已回复', '约面试', '已面试', '已offer', '已拒绝'];
  const rows = apps.map((a) => `
    <tr data-id="${esc(a.id)}">
      <td><b>${esc(a.company)}</b><div class="small muted">${esc(a.recruiter || '')}</div></td>
      <td>${esc(a.position)}<div class="small muted">${esc(a.city)} · ${esc(a.salary)}</div></td>
      <td><span class="chip mute">${esc(a.activity || '未标注')}</span></td>
      <td><select data-status="${esc(a.id)}">${STATUSES.map((s) => `<option ${s === a.status ? 'selected' : ''}>${s}</option>`).join('')}</select></td>
      <td class="small">${esc((a.greetedAt || '').slice(0, 16).replace('T', ' '))}</td>
      <td class="small">${a.resumeSentAt ? '✓' : '—'}<div class="small muted">${esc(a.review || '')}</div></td>
      <td><button class="sm" data-tl="${esc(a.id)}">时间线</button>
          <button class="sm" data-fb="${esc(a.id)}">加反馈</button></td>
    </tr>
    <tr class="tlrow" data-tlrow="${esc(a.id)}" style="display:none"><td colspan="7">
      <div class="timeline">${(a.timeline || []).map((t) => `<div class="t"><b class="small">${esc(t.event)}</b>
        <span class="small muted"> ${esc((t.at || '').slice(0, 16).replace('T', ' '))}</span>
        <div class="small">${esc(t.note || '')}</div></div>`).join('') || '<span class="muted small">无记录</span>'}</div>
    </td></tr>`).join('');
  return `
  <div class="card"><h3>投递记录 <span class="tag">共 ${apps.length} 家；状态列可直接修改</span></h3>
    <div class="tablewrap"><table><thead><tr><th>公司</th><th>岗位</th><th>活跃度</th><th>状态</th><th>打招呼</th><th>简历</th><th>操作</th></tr></thead>
    <tbody>${rows}</tbody></table></div>
  </div>
  <div class="card"><h3>记录一条反馈 <span class="tag">会把状态自动推进</span></h3>
    <div class="grid g3">
      <div class="field"><label>公司</label><select id="fbCompany">${apps.map((a) => `<option value="${esc(a.id)}">${esc(a.company)}</option>`).join('')}</select></div>
      <div class="field"><label>类型</label><select id="fbType">
        <option value="reply">HR 回复</option><option value="interview">约面试</option>
        <option value="interviewed">已面试</option><option value="offer">发 offer</option>
        <option value="reject">拒绝 / 不合适</option></select></div>
      <div class="field"><label>信号</label><select id="fbSignal"><option value="positive">积极</option><option value="neutral">中性</option><option value="negative">消极</option></select></div>
    </div>
    <div class="field"><label>内容</label><textarea id="fbContent" placeholder="粘贴 HR 原话或你的记录"></textarea></div>
    <button class="primary" id="saveFb">保存反馈</button>
  </div>`;
};

let CUR_THEME = null;
function applyThemeVars(theme) {
  CUR_THEME = theme || {};
  const root = document.documentElement.style;
  // 字段是 camelCase（sideBg），CSS 变量是 kebab-case（--side-bg）：必须转换，否则不生效
  Object.keys(CUR_THEME).forEach((k) => {
    const kebab = k.replace(/[A-Z]/g, (m) => '-' + m.toLowerCase());
    root.setProperty('--' + kebab, CUR_THEME[k]);
  });
}

VIEWS.settings = async () => {
  let s;
  try { s = await api('/settings'); } catch (e) { s = { theme: {}, presets: {} }; }
  let llm = { base_url: '', model: '', api_key_masked: '', enabled: false };
  try { llm = await api('/llm-config'); } catch (e) {}
  const t = s.theme || {};
  const presets = Object.entries(s.presets || {}).map(([name]) =>
    `<button class="chip${name === s.presetName ? ' ok' : ''}" data-theme-preset="${esc(name)}">${esc(name)}</button>`).join('');
  return `
  <div class="card"><h3>通用设置 <span class="tag">主题色 · 背景色</span></h3>
    <div class="field" style="margin-bottom:10px"><label>预设主题</label>
      <div class="row" style="gap:6px;flex-wrap:wrap">${presets || '<span class="small muted">（无）</span>'}</div>
    </div>
    <div class="grid g3">
      <div class="field"><label>侧栏背景色</label><input type="color" id="setSideBg" value="${esc(t.sideBg || '#5a5480')}" style="height:34px;padding:2px"></div>
      <div class="field"><label>页面背景色</label><input type="color" id="setBg" value="${esc(t.bg || '#f4f6f8')}" style="height:34px;padding:2px"></div>
      <div class="field"><label>主题色（按钮/高亮）</label><input type="color" id="setBrand" value="${esc(t.brand || '#8b5cf6')}" style="height:34px;padding:2px"></div>
    </div>
    <div class="row" style="margin-top:10px">
      <button class="primary" id="saveTheme">保存主题</button>
      <button id="resetTheme">恢复默认（灰紫）</button>
    </div>
    <p class="small muted" style="margin-top:8px">点击预设主题立即应用并保存；或自定义背景色/主题色后点「保存主题」。</p>
  </div>
  <div class="card"><h3>LLM 增强 <span class="tag">可选 · 不配置则纯规则分析</span></h3>
    <div class="small muted" style="margin-bottom:8px">开启后，岗位洞察会调 LLM 二次确认硬差距维度（看项目 bullet 有没有相关经验），避免规则误判。兼容任何 OpenAI 兼容网关（豆包方舟 / DeepSeek / OpenRouter / Moonshot / 通义 / 智谱）。</div>
    <div class="field" style="margin-bottom:8px"><label>状态</label>
      <span style="display:inline-block;padding:3px 10px;border-radius:12px;font-size:12px;font-weight:600;${llm.enabled ? 'background:#8b5cf6;color:#fff' : 'background:#e5e7eb;color:#6b7280'}">${llm.enabled ? '● 已启用（' + esc(llm.model) + '）' : '○ 未配置（纯规则模式）'}</span>
    </div>
    <div class="grid g3">
      <div class="field"><label>Base URL</label><input id="llmBase" value="${esc(llm.base_url || 'https://ark.cn-beijing.volces.com/api/v3')}" placeholder="https://ark.cn-beijing.volces.com/api/v3"></div>
      <div class="field"><label>模型名 / 端点 ID</label><input id="llmModel" value="${esc(llm.model)}" placeholder="如 ep-xxx 或 deepseek-chat"></div>
      <div class="field"><label>API Key${llm.api_key_masked ? ` <span class="small muted">（当前：${esc(llm.api_key_masked)}）</span>` : ''}</label>
        <input id="llmKey" type="password" placeholder="${llm.api_key_masked ? '留空保留原 key' : 'sk-...'}"></div>
    </div>
    <div class="row" style="margin-top:8px"><button class="primary" id="saveLlm">保存 LLM 配置</button></div>
  </div>
  <div class="card"><h3>BOSS 采集通道 <span class="tag">刷新岗位 / 投递的通道</span></h3>
    <div class="small" id="daemonState" style="margin-bottom:8px">检测中…</div>
    <div class="row"><button id="daemonToggle" class="primary">启动采集</button></div>
    <p class="small muted" style="margin-top:10px">服务连接：<span id="health2" class="pill">…</span> · 数据目录：<span class="mono">data/</span> · 左下角圆点为采集通道状态灯</p>
  </div>
  <div class="card"><h3>数据迁移 <span class="tag">整个 data 目录打包备份</span></h3>
    <div class="row"><button class="primary" id="doExport">导出备份（zip）</button><button id="doImport">从备份恢复</button></div>
    <p class="small muted" style="margin-top:10px">导出会打包 <span class="mono">data/</span> 全部文件并下载 <span class="mono">boss-workbench-backup.zip</span>；
    恢复会用上次导出的备份覆盖当前数据（建议先导出再恢复）。迁移到新机器：拷贝整个 <span class="mono">workbench/</span> 目录（含 data/ 与 web/），
    然后 <span class="mono">python3 workbench/server.py</span> 即可，无需安装任何依赖。</p>
  </div>`;
};

/* ------------------------------------------------------------ rendering -- */
const TITLES = { overview: ['概览', '投递漏斗、转化率与最新反馈'], profile: ['个人履历', '简历生成与技能匹配的唯一事实来源'],
  search: ['搜岗', '搜岗配置与岗位池'], strategy: ['投递与反馈', '策略 / 简历模板 / 记录反馈（Tab 切换）'],
  skills: ['岗位洞察', '目标岗位技术栈 / 高频技能 / 匹配度与缺口'], gap: ['差距与学习', '从岗位洞察进入的补强方案'],
  settings: ['设置', '主题色 / 背景色 / 数据迁移'] };
const TABS_CSS = '';   // .tabs 样式已移入 style.css

async function route() {
  const raw = location.hash.replace('#/', '') || 'overview';
  const [path, qs] = raw.split('?');
  const segs = path.split('/').filter(Boolean);
  let base = segs[0] || 'overview';
  const sub = segs[1] || '';
  const q = Object.fromEntries(new URLSearchParams(qs || ''));
  // 兼容旧链接 & 子页面
  if (base === 'config') base = 'search';
  if (base === 'jobs') { base = 'search'; q.tab = 'jobs'; }
  if (base === 'apps') base = 'strategy';   // 旧链接兼容（已与投递策略合并）
  if (base === 'data') base = 'settings';   // 数据迁移已并入设置页
  if (base === 'skills' && sub === 'gap') base = 'skills';
  if (base === 'gap') base = 'skills';   // 差距与学习已并入岗位洞察
  CUR = q;

  const fn = VIEWS[base] || VIEWS.overview;
  const navKey = base === 'gap' ? 'skills' : base;
  $$('#nav a').forEach((a) => a.classList.toggle('on', a.dataset.v === navKey));
  const el = $('#view');
  el.innerHTML = '<div class="empty">加载中…</div>';
  try { el.innerHTML = await fn(q); } catch (e) { el.innerHTML = `<div class="empty">加载失败：${esc(e.message)}</div>`; }
  HOOKS[base]?.();
  // 「重新分析」按钮在渲染后才存在：绑定必须在渲染后取 DOM，否则首次进入绑到旧元素导致无效
  const ab = $('#btnAnalyze');
  if (ab) ab.onclick = async () => {
    toast('正在分析…');
    const r = await api('/analyze', { method: 'POST', body: {} });
    if (r.ok) {
      const out = r.stdout || '';
      const dm = out.match(/\[delta\]\s*([^\n]+)/);
      if (dm && /mode=noop/.test(dm[1])) {
        toast('无变化：岗位池和履历都没更新，复用上次结果');
      } else if (dm) {
        toast('分析已更新：' + dm[1].replace('mode=', '模式 ').replace(/added=(\d+).*?changed=(\d+).*?removed=(\d+).*?kept=(\d+)/, '新增$1 · 重算$2 · 移除$3 · 沿用$4'));
      } else {
        toast('岗位洞察与差距分析已更新');
      }
    } else {
      toast('分析失败：' + (r.stderr || r.error || '').slice(0, 80), true);
    }
    if (r.ok) route();
  };
}

HOOKS.search = () => { HOOKS.searchConfig?.(); HOOKS.jobPool?.(); HOOKS.searchTargets?.(); };
HOOKS.searchTargets = () => bindSearchTargets();

function setPath(obj, path, val) {
  const ks = path.split('.');
  let o = obj;
  for (let i = 0; i < ks.length - 1; i++) {
    const k = ks[i];
    if (o[k] == null) o[k] = /^\d+$/.test(ks[i + 1]) ? [] : {};
    o = o[k];
  }
  o[ks[ks.length - 1]] = val;
}
function getPath(obj, path) {
  const ks = (path || '').split('.');
  let o = obj;
  for (const k of ks) {
    if (o == null || o[k] === undefined) return undefined;
    o = o[k];
  }
  return o;
}

/* 列表字段多分隔符解析：技术栈宽拆（逗号/顿号/分号/斜杠/换行/中点，保留 + 与 - 连接的技术词）；
   亮点/职责等长句保守拆（换行 + 分号 + 行首项目符号 •·-，逗号/顿号保留在句内） */
function splitList(path, value) {
  const key = String(path || '').split('.').pop();
  const stripMark = (s) => s.replace(/^[•·\-\s]+/, '').trim();
  if (key === 'stack' || key === 'techstack' || key === 'tech') {
    // 「 + 」组合技术视为分隔（PostgreSQL + pgvector → 两条独立技术词）
    return value.replace(/\s*\+\s*/g, '、').split(/[，,、;；/ \n\r·]+/).map(stripMark).filter(Boolean);
  }
  return value.split(/\r?\n/)
    .map((l) => l.trim()).filter(Boolean)
    .flatMap((l) => l.split(/[；;]+/).map(stripMark).filter(Boolean));
}

function syncProfileFromDom() {
  // 先按原索引写回所有 data-p 字段（保持 skills 数组布局不变），最后再重建「专业技能」组，
  // 避免数组重排后 data-p 按旧索引写回造成错位覆盖
  $$('[data-p]').forEach((el) => {
    const v = el.type === 'checkbox' ? el.checked
      : el.dataset.list ? splitList(el.dataset.p, el.value)
        : el.dataset.num ? (Number(el.value) || 0)
          : el.value;
    setPath(PDRAFT, el.dataset.p, v);
  });
  // 简历字段显示开关状态收集（点击时已即时更新 PDRAFT.contactVisibility，这里只读出来）
  // 个人简介三行（定位 / 成果 / 稀缺）→ 兼容字段 summary（换行拼接，供 LLM 定制与旧渲染引用）
  const _pos = String(PDRAFT.summaryPosition || '').trim();
  const _res = String(PDRAFT.summaryResult || '').trim();
  const _rar = String(PDRAFT.summaryRarity || '').trim();
  PDRAFT.summary = [_pos, _res, _rar].filter(Boolean).join('\n');
  // 技能区简化编辑：textarea 每行一个技能名（不再按顿号/逗号拆分）→ 重建该组条目
  $$('[data-skills]').forEach((el) => {
    const g = el.dataset.skills;
    const names = [...new Set(el.value.split(/\r?\n/).map((x) => x.trim()).filter(Boolean))];
    const old = (PDRAFT.skills || []).filter((s) => (s.group || 'professional') === g);
    const byName = new Map(old.map((s) => [(s.name || '').trim(), s]));
    const merged = names.map((n) => {
      const ex = byName.get(n);
      return ex ? Object.assign({}, ex, { name: n }) : blankSkill(g, n);
    });
    PDRAFT.skills = (PDRAFT.skills || []).filter((s) => (s.group || 'professional') !== g).concat(merged);
  });
}

function rerenderProfile() { $('#view').innerHTML = profileHtml(); bindProfile(); }

function bindProfile() {
  // 眼睛 icon 点击切换：document 事件委托，只绑一次（页面加载即生效，不依赖 syncProfileFromDom）
  PDRAFT.contactVisibility = PDRAFT.contactVisibility || {};
  if (!window.__visDelegated) {
    window.__visDelegated = true;
    const svgOn = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:block"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>';
    const svgOff = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:block"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>';
    document.addEventListener('click', (e) => {
      const el = e.target.closest('.vis-eye');
      if (!el) return;
      e.preventDefault(); e.stopPropagation();
      const k = el.dataset.vis;
      const cur = PDRAFT.contactVisibility[k] !== false;
      const next = !cur;
      PDRAFT.contactVisibility[k] = next;
      el.style.color = next ? '#2b6cb0' : '#a0aec0';
      el.innerHTML = next ? svgOn : svgOff;
      el.title = next ? '在简历上显示（点击隐藏）' : '不在简历上显示（点击显示）';
    });
  }
  // 字数统计：输入框右下角实时显示 实际字数/推荐字数（data-count 标记，.field 内 .ccount 承接）
  $$('[data-count]').forEach((el) => {
    const upd = () => {
      const c = el.closest('.field') && el.closest('.field').querySelector('.ccount');
      if (c) c.textContent = el.value.trim().length + '/40';
    };
    el.addEventListener('input', upd);
    upd();
  });
  // 板块折叠：点击标题行切换展开/收起，状态记 localStorage（重渲染后恢复）
  $$('.card.collapsible[data-collapse]').forEach((card) => {
    const head = card.querySelector('.sec-head');
    if (!head) return;
    head.onclick = (e) => {
      if (e.target.closest('button, input, textarea, a, label')) return;
      const collapsed = card.classList.toggle('collapsed');
      try { localStorage.setItem(COLLAPSE_KEY + card.dataset.collapse, collapsed ? '1' : ''); } catch (err) { /* 隐私模式下忽略 */ }
    };
  });
  // 目标岗位管理已移至「搜岗」页（最大前提）；本页只读展示求职方向（简历标题）
  // 侧边大纲：点击定位 + 滚动高亮
  const tocEls = $$('.profile-toc [data-jump]');
  if (tocEls.length) {
    tocEls.forEach((a) => (a.onclick = (e) => {
      e.preventDefault();
      const t = document.getElementById(a.dataset.jump);
      if (!t) return;
      if (t.tagName === 'DETAILS' && !t.open) t.open = true;
      if (t.classList && t.classList.contains('collapsed')) {          // 折叠板块：先展开再定位
        t.classList.remove('collapsed');
        try { localStorage.setItem(COLLAPSE_KEY + t.dataset.collapse, ''); } catch (err) { /* ignore */ }
      }
      // 等下一帧（展开后布局稳定）再平滑滚动，避免折叠时 scrollIntoView 定位错
      setTimeout(() => t.scrollIntoView({ behavior: 'smooth', block: 'start' }), 60);
    }));
    const targets = tocEls.map((a) => document.getElementById(a.dataset.jump)).filter(Boolean);
    const spy = () => {
      let cur = targets[0];
      for (const t of targets) if (t.getBoundingClientRect().top <= 140) cur = t;
      tocEls.forEach((a) => a.classList.toggle('on', cur && a.dataset.jump === cur.id));
    };
    window.removeEventListener('scroll', window.__tocSpy || (() => {}));
    window.__tocSpy = spy;
    window.addEventListener('scroll', spy, { passive: true });
    spy();
  }
  $$('[data-delitem]').forEach((b) => (b.onclick = () => {
    syncProfileFromDom();
    const [k, i] = b.dataset.delitem.split(':');
    (PDRAFT[k] || []).splice(+i, 1);
    rerenderProfile();
  }));
  // rank 控件（标题栏 + 内容区）：点开浮层不触发折叠切换；行点击走插入式顺延；点击页面其他处关闭浮层
  $$('.rankpick').forEach((pk) => {
    pk.addEventListener('click', (e) => {
      e.stopPropagation();
      const row = e.target.closest('.rp-row');
      if (row) {
        shiftRankInto(pk.dataset.rpath, Number(row.dataset.rankval) || 0);
        refreshRankUI();
        return;
      }
      const list = pk.querySelector('.rp-list');
      const isOpen = list.style.display !== 'none';
      $$('.rp-list').forEach((l) => { l.style.display = 'none'; });
      if (!isOpen) list.style.display = 'block';
    });
  });
  // 点击页面其他处关闭 rank 浮层（全局只注册一次，避免重渲染累积监听）
  if (!window.__rankDocClick) {
    window.__rankDocClick = 1;
    document.addEventListener('click', () => {
      $$('.rp-list').forEach((l) => { l.style.display = 'none'; });
    });
  }
  // 工作经历内嵌子项目：添加 / 删除
  $$('[data-addsub]').forEach((b) => (b.onclick = () => {
    syncProfileFromDom();
    const ei = +b.dataset.addsub;
    const exp = (PDRAFT.experiences || [])[ei];
    if (!exp) return;
    exp.subProjects = exp.subProjects || [];
    exp.subProjects.push(blankSubProject());
    rerenderProfile();
  }));
  $$('[data-delsub]').forEach((b) => (b.onclick = () => {
    syncProfileFromDom();
    const [ei, si] = b.dataset.delsub.split(':');
    const exp = (PDRAFT.experiences || [])[+ei];
    if (!exp || !exp.subProjects) return;
    exp.subProjects.splice(+si, 1);
    rerenderProfile();
  }));
  // 项目排序统一由「核心项目排名」rank 下拉接管（1-5），不再提供上移/下移
  ['education', 'experiences', 'projects'].forEach((k) => {
    const btn = $('#add-' + k);
    if (btn) btn.onclick = () => {
      syncProfileFromDom();
      (PDRAFT[k] = PDRAFT[k] || []).push(blank(k));
      rerenderProfile();
    };
  });
  // 四大分类各自的「添加」按钮：添加后直接展开该分类，进入编辑状态
  $$('[data-addgroup]').forEach((b) => (b.onclick = () => {
    syncProfileFromDom();
    const g = b.dataset.addgroup;
    (PDRAFT.skills = PDRAFT.skills || []).push(blankSkill(g));
    rerenderProfile();
    const sec = $('#sec-' + g);
    if (sec) sec.open = true;
  }));

/* 目标岗位：从目标管理 DOM（搜岗页）收集 targets/activeTarget，并同步 title（简历标题） */
$('#saveProfile').onclick = async () => {
  syncProfileFromDom();
  (PDRAFT.skills || []).forEach((s) => { if (s.evidenceLevel == null) s.evidenceLevel = inferLevel(s.statement || ''); });
    try {
      await api('/profile', { method: 'PUT', body: PDRAFT });
      toast('履历已保存');
      route();
    } catch (e) {
      if (e.status === 409) {          // 页面里的副本过期，拒绝覆盖服务端
        toast(e.message, true);
        setTimeout(() => route(), 1800);
      } else {
        toast('保存失败：' + e.message.slice(0, 60), true);
      }
    }
  };
  // 异步加载简历模板列表，填充 #genTpl 下拉
  api('/resume/templates').then((r) => {
    const sel = $('#genTpl');
    if (!sel) return;
    const cur = sel.value;
    const opts = (r.templates || []).map((t) =>
      `<option value="${esc(t.name)}" ${t.name === r.default ? 'selected' : ''}>${esc(t.name.replace(/\.html$/, ''))}${t.builtin ? '（内置）' : ''}</option>`).join('');
    sel.innerHTML = `<option value="">默认（${esc((r.default || 'resume.html').replace(/\.html$/, ''))}）</option>` + opts;
    if (cur) sel.value = cur;
  }).catch(() => {});
  $('#genResume').onclick = async () => {
    const btn = $('#genResume');
    const tid = ($('#genTarget') || {}).value || '';
    const tpl = ($('#genTpl') || {}).value || '';
    btn.disabled = true;
    const old = btn.textContent;
    btn.textContent = '生成中…';
    try {
      // 先把当前未保存的修改存盘，避免 PDF 用的是旧 profile
      syncProfileFromDom();
      (PDRAFT.skills || []).forEach((s) => { if (s.evidenceLevel == null) s.evidenceLevel = inferLevel(s.statement || ''); });
      await api('/profile', { method: 'PUT', body: PDRAFT });
      const r = await api('/resume/generate', { method: 'POST', body: { targetId: tid || undefined, templateName: tpl || undefined } });
      toast(`已生成 PDF（${(r.pdfBytes / 1024).toFixed(0)} KB，模板 ${r.templateName}），正在打开…`);
      // 新标签页打开 PDF（浏览器内联预览），同时触发下载
      window.open(r.pdfUrl, '_blank');
      setTimeout(() => {
        const a = document.createElement('a');
        a.href = r.pdfUrl; a.download = r.fileStem + '.pdf';
        document.body.appendChild(a); a.click(); a.remove();
      }, 600);
    } catch (e) {
      toast('生成失败：' + (e.message || '').slice(0, 120), true);
    } finally {
      btn.disabled = false;
      btn.textContent = old;
    }
  };
  $('#saveRaw').onclick = async () => {
    PDRAFT = JSON.parse($('#rawProfile').value);
    await api('/profile', { method: 'PUT', body: PDRAFT });
    toast('已保存'); rerenderProfile();
  };
}

/* 目标岗位：从目标管理 DOM（搜岗页）收集 targets/activeTarget，并同步 title（简历标题） */
function collectRowsFromDom(p) {
  const rows = [...document.querySelectorAll('#targetList [data-trow]')];
  p.targets = rows.map((r) => ({
    id: r.dataset.tid,
    title: ((r.querySelector('[data-ttitle]') || {}).value || '').trim(),
    keywords: String(((r.querySelector('[data-tkw]') || {}).value) || '').split(/[，,、;；]+/).map((s) => s.trim()).filter(Boolean),
    note: '',
  }));
  const act = document.querySelector('#targetList [data-tactive]:checked');
  p.activeTarget = act ? act.value : ((p.targets[0] || {}).id) || null;
  const cur = p.targets.find((t) => t.id === p.activeTarget) || p.targets[0] || {};
  p.title = cur.title || '';
  return p;
}

HOOKS.profile = () => bindProfile();

HOOKS.searchConfig = () => {
  const cur = async () => api('/config');
  let cfg;
  cur().then((c) => (cfg = c));
  const save = async () => { await api('/config', { method: 'PUT', body: cfg }); toast('配置已保存'); route(); };
  let advOn = false;
  const applyAdv = () => $$('#cityBody .adv').forEach((e) => (e.style.display = advOn ? '' : 'none'));
  const bindCityRows = () => {
    $$('#cityBody [data-c]').forEach((i) => (i.onchange = () => {
      const [a, b, c] = i.dataset.c.split('.');
      cfg[a][b][c] = c === 'priority' ? +i.value : i.value;
    }));
    $$('#cityBody [data-cdel]').forEach((b) => (b.onclick = () => { cfg.cities.splice(+b.dataset.cdel, 1); renderCities(); }));
  };
  const renderCities = () => { $('#cityBody').innerHTML = cityRowHtml(cfg.cities || []); applyAdv(); bindCityRows(); };
  bindCityRows();
  // 增删只改本地草稿并重渲染，不自动保存 —— 由右下角「保存配置」统一生效
  $('#addCity').onclick = () => { (cfg.cities = cfg.cities || []).push({ name: '新城市', code: '', priority: 9 }); renderCities(); };
  const toggle = $('#cfgToggle');
  if (toggle) toggle.onclick = () => {
    const body = $('#cfgBody');
    const open = body.style.display !== 'none';
    body.style.display = open ? 'none' : '';
    toggle.textContent = open ? '展开编辑 ▾' : '收起 ▲';
  };
  $('#saveConfig').onclick = async () => {
    cfg = cfg || (await cur());
    cfg.salary = { ...(cfg.salary || {}), min: +$('#salMin').value, max: +$('#salMax').value };
    cfg.batch_size = +$('#batch').value;
    cfg.activity_preference = $$('[data-act]').filter((i) => i.checked).map((i) => i.dataset.act);
    cfg.recruit_types = $$('[data-rt]').filter((i) => i.checked).map((i) => i.dataset.rt);
    delete cfg.exclude_title_keywords;   // 已弃用：不再按岗位关键词排除
    await save();
  };
  $('#reloadConfig').onclick = () => route();
  const adv = $('#showAdv');
  if (adv) adv.onchange = () => { advOn = adv.checked; applyAdv(); };
};


HOOKS.strategyForm = () => {
  const runBatchNow = $('#runBatchNow'), runBatchOut = $('#runBatchOut');
  if (runBatchNow) runBatchNow.onclick = async () => {
    runBatchNow.disabled = true; runBatchNow.textContent = '任务运行中…';
    let r;
    try { r = await api('/run-batch', { method: 'POST' }); } catch (e) { r = { ok: false, error: e.message }; }
    runBatchNow.disabled = false; runBatchNow.textContent = '▶ 运行';
    if (runBatchOut) runBatchOut.style.display = 'block';
    if (r && r.ok) {
      const codeMap = { 0: '可开工：有候选岗位，可进入投递流程', 2: '无候选岗位：本轮无需行动', 3: '策略暂停：先复盘调整' };
      const reason = codeMap[r.code] || ('退出码 ' + r.code);
      if (runBatchOut) runBatchOut.textContent = `退出码 ${r.code} → ${reason}\n\n` + (r.output || '').slice(0, 700);
      modal(`任务已执行：${reason}`, r.code === 0);
    } else {
      if (runBatchOut) runBatchOut.textContent = '执行失败：' + ((r && r.error) || '未知错误');
      modal('任务执行失败：' + ((r && r.error) || '').slice(0, 60), false);
    }
  };
  $('#saveStrategy').onclick = async () => {
    const st = await api('/strategy');
    st.enabled = $('#stEnabled').value === 'true';
    st.mode = $('#stMode').value;
    st.cadence = {
      type: $('#stCadType').value,
      times: $('#stTimes').value.split(',').map((x) => x.trim()).filter(Boolean),
      weekdays: $$('[data-wd]').filter((i) => i.checked).map((i) => +i.dataset.wd),
      interval_hours: +$('#stInterval').value || 0,
    };
    st.batch_size = +$('#stBatch').value;
    st.daily_limit = +$('#stDaily').value;
    st.time_windows = [{ from: $('#stWinFrom').value, to: $('#stWinTo').value }];
    st.require_approval = $('#stApproval').value === 'true';
    st.auto_apply = !st.require_approval;
    st.pause_after_consecutive_no_reply = +$('#stPause').value;
    st.min_reply_rate = +$('#stMinRate').value;
    st.dedupe_days = +$('#stDedupe').value;
    st.per_company_cooldown_days = +$('#stCooldown').value;
    st.max_per_company = +$('#stMaxCo').value;
    st.stop_on_risk_control = $('#stRisk').checked;
    st.review_gate = { deterministic: $('#stGateDet').checked, independent_agent: $('#stGateAgent').checked };
    await api('/strategy', { method: 'PUT', body: st });
    toast('投递策略已保存'); route();
  };
  $('#reloadStrategy').onclick = () => route();
};

HOOKS.jobPool = () => {
  let all = [];
  let tgt = { id: '', title: '', kws: [] };   // 当前选中目标：岗位池 = 该目标采集的岗位
  let page = 1, pageSize = 20, viewAll = false;   // viewAll=true 时跨目标展示全部
  let cfg = {};                                  // 搜岗配置（活跃度偏好等；加载完成前按「不限」处理）
  api('/config').then((c) => { cfg = c || {}; render(); }).catch(() => {});

  const salaryMid = (s) => {                 // "30-50K·15薪" → 40；"200-400元/天" → 按 20 个工作日折月薪；"未标注" → 0
    const t = s || '';
    const m = /(\d+(?:\.\d+)?)\s*[-~—]\s*(\d+(?:\.\d+)?)/.exec(t);
    if (!m) return 0;
    const mid = (parseFloat(m[1]) + parseFloat(m[2])) / 2;
    return /元\/天|时薪/.test(t) ? mid * 20 / 1000 : mid;   // 日薪按 20 个工作日折成 K 值（元 → 千元）
  };
  const actRank = (j) => {
    const a = j.activity || '';
    const base = ({ '刚刚活跃': 5, '今日活跃': 4, '3日内活跃': 3, '本周活跃': 2, '本月活跃': 1, '月内活跃': 1 })[a] || 0;
    if (base) return base;
    // BOSS 已移除活跃度标签：按 lastSeenAt 新鲜度排（最近采集=权重 3，一周内=2，两周内=1，更老=0）
    const d = _daysAgo(j.lastSeenAt);
    if (d == null) return 0;
    if (d <= 1) return 3;
    if (d <= 7) return 2;
    if (d <= 14) return 1;
    return 0;
  };
  const hitN = (j) => {                     // 目标关键词命中数（排序用）
    if (!tgt.kws.length) return 0;
    const s = (j.position + ' ' + (j.jd || '')).toLowerCase();
    return tgt.kws.filter((k) => s.includes(k.toLowerCase())).length;
  };

  const ownPoolCount = () => tgt.id ? all.filter((j) => (j.targetIds || []).includes(tgt.id) || j.targetId === tgt.id).length : 0;

  const applySort = (list, mode) => {
    const arr = list.slice();
    if (mode === 'active') arr.sort((a, b) => actRank(b) - actRank(a));
    else if (mode === 'salary') arr.sort((a, b) => salaryMid(b.salary) - salaryMid(a.salary));
    else if (mode === 'new') arr.sort((a, b) => String(b.collectedAt).localeCompare(String(a.collectedAt)));
    else arr.sort((a, b) => (hitN(b) - hitN(a)) || (actRank(b) - actRank(a)) || (salaryMid(b.salary) - salaryMid(a.salary)));
    return arr;
  };

  const render = () => {
    const city = $('#fCity').value, kw = $('#fKw').value.trim().toLowerCase(),
          type = $('#fType').value, ml = (($('#fMatch') || {}).value || ''),
          act = (($('#fActive') || {}).value || ''), sort = ($('#fSort') || {}).value || 'match';
    const actWanted = act === 'cfg' ? (cfg.activity_preference || []) : (act ? [act] : []);
    // 岗位池 = 当前目标采集的岗位（targetIds 归属）；viewAll 或目标无 id 时跨目标展示
    const ownPool = tgt.id ? all.filter((j) => (j.targetIds || []).includes(tgt.id) || j.targetId === tgt.id) : [];
    const base = viewAll || !tgt.id ? all : ownPool;
    const filtered = base.filter((j) => (!city || j.city === city) &&
      (!type || (j.recruitType || '') === type) &&
      (!ml || (j.matchLevel || '') === ml) &&
      (!actWanted.length || !(j.activity || '').trim() || actWanted.includes(j.activity)) &&
      (!kw || (j.company + j.position + (j.jd || '')).toLowerCase().includes(kw)));
    const list = applySort(filtered, sort);
    const pages = Math.max(1, Math.ceil(list.length / pageSize));
    if (page > pages) page = pages;
    const slice = list.slice((page - 1) * pageSize, page * pageSize);

    const pm = $('#poolMatch'), fc = $('#fCount'), pf = $('#poolFresh');
    if (pm) {
      const nStrong = ownPool.filter((j) => j.matchLevel === 'strong').length;
      const nWeak = ownPool.filter((j) => j.matchLevel === 'weak').length;
      if (viewAll) pm.textContent = `全部岗位（跨目标）${all.length} 条`;
      else if (ownPool.length) pm.textContent = tgt.kws.length
        ? `跟随顶部目标「${esc(tgt.title || '（未命名）')}」 · ${ownPool.length} 条 · ≥60% 高匹配 ${nStrong} / 35-59% 中匹配 ${nWeak} / 低匹配 ${ownPool.length - nStrong - nWeak}` : `跟随顶部目标「${esc(tgt.title || '（未命名）')}」 · ${ownPool.length} 条 · 无关键词按活跃度排序`;
      else pm.textContent = `顶部目标「${esc(tgt.title || '（未命名）')}」暂无岗位 · 全池 ${all.length} 条属其他目标`;
    }
    if (pf) pf.textContent = all.length ? `最近采集 ${(all.slice().sort((a, b) => String(b.collectedAt).localeCompare(String(a.collectedAt)))[0].collectedAt || '').slice(0, 16)}` : '';
    if (fc) fc.textContent = `共 ${list.length} 条`;

    $('#jobBody').innerHTML = slice.length ? slice.map((j) => {
      const fresh = j.firstSeenAt && (Date.now() - new Date(j.firstSeenAt.replace('T', ' ')).getTime()) < 48 * 3600 * 1000;
      const mlChip = j.matchScore != null
        ? `<span class="chip small ${j.matchScore >= 60 ? 'on' : j.matchScore >= 35 ? '' : 'mute'}" title="岗位 × 履历 层级匹配度（jd_match_v1：命中 ${j.matchDims || '?'} 个需求维度，L1-L4 语义匹配率，超配不计分）">${j.matchScore}%</span>`
        : '<span class="chip mute small" title="无 JD/未重算匹配度">—</span>';
      return `<tr class="jobrow" data-job="${esc(j.id || j.uid)}">
      <td><b>${esc(j.company)}</b></td><td>${esc(j.position)}${fresh ? ' <span class="chip on small">新</span>' : ''}</td><td>${esc(j.city)}</td>
      <td class="mono">${esc(j.salary || '面议')}</td><td class="small">${esc(j.experience || '')}<div class="muted">${esc(j.degree || '')}</div></td>
      <td><span class="chip ${j.recruitType === '校招' ? 'on' : 'mute'}">${esc(j.recruitType || '-')}</span></td>
      <td>${mlChip}</td>
      <td class="small">${(j.skillTags || []).slice(0, 6).map((s) => `<span class="chip mute small">${esc(s)}</span>`).join(' ')}</td>
      <td class="small">${actChip(j)}</td></tr>`;
    }).join('')
      : `<tr><td colspan="9"><div class="empty" style="padding:28px">
          目标「${esc(tgt.title || '（未命名）')}」还没有采集岗位。<br>
          展开上方「目标岗位」设置搜索关键词后，由 Agent 按它采集（当前全池 ${all.length} 条属于其他目标）。
          <div style="margin-top:10px"><button id="poolViewAll" class="sm">查看全部岗位（跨目标）</button></div>
        </div></td></tr>`;

    // 分页条：‹ 页码 … › + 每页选择
    const pg = $('#pager');
    if (pg) {
      const btns = [`<button class="sm ghost" data-pg="${page - 1}" ${page <= 1 ? 'disabled' : ''}>‹ 上一页</button>`];
      const from = Math.max(1, page - 2), to = Math.min(pages, page + 2);
      if (from > 1) btns.push(`<span class="small muted">…</span>`);
      for (let i = from; i <= to; i++) btns.push(`<button class="sm ${i === page ? 'primary' : 'ghost'}" data-pg="${i}">${i}</button>`);
      if (to < pages) btns.push(`<span class="small muted">…</span>`);
      btns.push(`<button class="sm ghost" data-pg="${page + 1}" ${page >= pages ? 'disabled' : ''}>下一页 ›</button>`);
      btns.push(`<span class="small muted">第 ${page} / ${pages} 页</span>`);
      btns.push(`<select id="pgSize" style="width:auto"><option value="20" ${pageSize === 20 ? 'selected' : ''}>20 条/页</option><option value="50" ${pageSize === 50 ? 'selected' : ''}>50 条/页</option><option value="100" ${pageSize === 100 ? 'selected' : ''}>100 条/页</option></select>`);
      pg.innerHTML = btns.join('');
      pg.onclick = (e) => {
        const b = e.target.closest('button[data-pg]');
        if (b && !b.disabled) { page = +b.dataset.pg; render(); }
      };
      const ps = $('#pgSize');
      if (ps) ps.onchange = () => { pageSize = +ps.value; page = 1; render(); };
    }
    const va = $('#poolViewAll');
    if (va) va.onclick = () => { viewAll = true; page = 1; render(); };
  };

  const loadJobs = () => api('/jobs').then((d) => { all = d; render(); }).catch(() => render());
  // 首次进入搜岗页：岗位池尚无匹配度时，自动触发一次批量重算（jd_match 单岗层级匹配，~1-2s），
  // 相关度列即为「岗位 × 履历 匹配度百分比」
  const autoMatch = () => {
    if (all.some((j) => j.matchScore != null)) return;
    api('/jobs/match', { method: 'POST', body: { target: tgt.id } })
      .then((r) => {
        if (r && r.ok && r.scored) { toast(`已重算 ${r.scored} 个岗位的匹配度`); return loadJobs(); }
      }).catch(() => {});
  };
  const loadTgt = () => api('/profile').then((p) => {
    const act = p.activeTarget || ((p.targets || [])[0] || {}).id || null;
    const cur = (p.targets || []).find((t) => t.id === act) || {};
    tgt = { id: act || '', title: cur.title || '', kws: (cur.keywords || []).slice() };
    viewAll = false; page = 1;               // 目标变化后回到"只看该目标池"
    render();
  }).catch(() => render());
  const load = () => Promise.all([loadJobs(), loadTgt()]).then(autoMatch);
  load();
  ['fCity', 'fKw', 'fType', 'fMatch', 'fActive', 'fSort'].forEach((id) => ($('#' + id).oninput = render));
  const cBtn = $('#poolClear');
  if (cBtn) cBtn.onclick = async () => {
    if (!tgt.id) return toast('当前无目标', true);
    if (!confirm(`清空目标「${tgt.title}」的全部岗位（共 ${ownPoolCount()} 条）？清空后可点「刷新」重新采集。`)) return;
    cBtn.disabled = true; cBtn.textContent = '清空中…';
    const r = await api('/jobs/clear', { method: 'POST', body: { target: tgt.id } }).catch((e) => ({ error: e.message }));
    cBtn.disabled = false; cBtn.textContent = '清空本目标岗位';
    if (r && r.ok) { toast(`已清空 ${r.removed} 条`); viewAll = false; page = 1; await load(); }
    else toast((r && r.error) || '清空失败', true);
  };
  const rBtn = $('#poolRefresh');
  if (rBtn) rBtn.onclick = async () => {
    rBtn.disabled = true; rBtn.textContent = '采集中…';
    const r = await api('/jobs/refresh', { method: 'POST', body: {} }).catch((e) => ({ error: e.message || '请求失败' }));
    if (r && r.ok && r.started) {
      // 采集态：每 3s 轮询采集状态 + 拉取岗位实时上屏（新岗位带「新」标，无需手动刷新）
      const poll = async () => {
        const st = await api('/jobs/refresh/status').catch(() => null);
        if (st && st.running) {
          const ph = st.phase === 'detail' ? '详情回填' : '列表采集';
          rBtn.textContent = `${ph}中…（${st.done}/${st.total} · 新增 ${st.added}${st.excluded ? ' · 剔除 ' + st.excluded : ''}）`;
        }
        await loadJobs();   // 全量拉取渲染，实时看到已采岗位
        if (st && st.running) { setTimeout(poll, 3000); return; }
        rBtn.disabled = false; rBtn.textContent = '🔄 从 BOSS 拉取';
        const f = st || {};
        toast(`采集完成：新增 ${f.added || 0} 条，更新 ${f.updated || 0} 条${f.error ? ' · ' + f.error : ''}`, !!f.error);
        viewAll = false; load();
      };
      poll();
    } else {
      rBtn.disabled = false; rBtn.textContent = '🔄 从 BOSS 拉取';
      toast((r && (r.error || r.code)) || '采集不可用', true);
    }
  };
  const pBtn = $('#poolPrune');
  if (pBtn) pBtn.onclick = async () => {
    pBtn.disabled = true; pBtn.textContent = '清理中…';
    const r = await api('/jobs/prune', { method: 'POST', body: {} }).catch((e) => ({ error: e.message }));
    pBtn.disabled = false; pBtn.textContent = '🧹 清理错配岗位';
    if (r && r.ok && r.report) {
      const rep = r.report;
      const rm = rep.removed_total || 0;
      toast(rm ? `清理完成：剔除校招 ${rep.school_removed.length} · 错配 ${rep.mismatch_removed.length} · 剥离归属 ${rep.detached.length}，保留 ${rep.kept} 条（清洗前已自动备份）` : '岗位池已干净，无需清理');
      viewAll = false; page = 1; await load();
    } else {
      toast((r && r.error) || '清理失败', true);
    }
  };
  const aBtn = $('#poolActRefresh');
  if (aBtn) aBtn.onclick = async () => {
    aBtn.disabled = true; aBtn.textContent = '刷新中…';
    const r = await api('/jobs/refresh-activity', { method: 'POST', body: {} }).catch((e) => ({ error: e.message }));
    if (r && r.ok && r.started) {
      const poll = async () => {
        const st = await api('/jobs/refresh/status').catch(() => null);
        if (st && st.running) {
          aBtn.textContent = `刷新活跃度…（${st.done}/${st.total}）`;
          await loadJobs();
          setTimeout(poll, 3000); return;
        }
        aBtn.disabled = false; aBtn.textContent = '⚡ 刷新活跃度';
        toast(`活跃度刷新完成`);
        load();
      };
      poll();
    } else {
      aBtn.disabled = false; aBtn.textContent = '⚡ 刷新活跃度';
      toast((r && (r.error || r.msg)) || '刷新不可用', true);
    }
  };
  const tbody = $('#jobBody');
  if (tbody) tbody.onclick = (e) => {
    const tr = e.target.closest('tr[data-job]');
    if (tr) openJobPanel(tr.dataset.job);
  };
  window.__jobPoolRefresh = (p) => {          // 目标切换/关键词变化时由目标区块联动刷新
    if (p) {
      const act = p.activeTarget || ((p.targets || [])[0] || {}).id || null;
      const cur = (p.targets || []).find((t) => t.id === act) || {};
      tgt = { id: act || '', title: cur.title || '', kws: (cur.keywords || []).slice() };
      viewAll = false; page = 1;
    }
    render();
  };
};

/* ------------------------------------------------- 岗位匹配分析右抽屉 -- */
function ensureJobPanel() {
  if ($('#jobPanel')) return;
  const d = document.createElement('div');
  d.innerHTML = `<div id="jobBackdrop" class="jbackdrop"></div>
    <aside id="jobPanel" class="jpanel">
      <div class="jhead">
        <div style="min-width:0"><div id="jpTitle" class="jptitle">岗位分析</div><div id="jpMeta" class="small muted" style="margin-top:2px"></div></div>
        <button id="jpClose" class="ghost sm">✕ 关闭</button>
      </div>
      <div id="jpBody" class="jbody"></div>
    </aside>`;
  document.body.appendChild(d);
  $('#jpClose').onclick = closeJobPanel;
  $('#jobBackdrop').onclick = closeJobPanel;
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeJobPanel(); });
}

function closeJobPanel() {
  const p = $('#jobPanel'), b = $('#jobBackdrop');
  if (p) p.classList.remove('open');
  if (b) b.classList.remove('show');
  setTimeout(() => { if (p) p.classList.add('hidden'); }, 220);
}

function openJobPanel(id) {
  ensureJobPanel();
  const p = $('#jobPanel'), b = $('#jobBackdrop');
  p.classList.remove('hidden'); p.classList.add('open'); b.classList.add('show');
  const body = $('#jpBody');
  body.innerHTML = '<div class="empty">正在计算与你的匹配度…</div>';
  api('/jobmatch?id=' + encodeURIComponent(id))
    .then((m) => renderJobPanel(m))
    .catch((e) => (body.innerHTML = '<div class="empty">加载失败：' + esc(e.message) + '</div>'));
}

function renderJobPanel(m) {
  const j = m.job || {};
  $('#jpTitle').textContent = (j.position || '未命名岗位') + ' · ' + (j.company || '');
  const days = _daysAgo(j.lastSeenAt);
  const actStr = j.activity || (days != null ? `采集于 ${days} 天前` : '');
  $('#jpMeta').textContent = [j.city, j.salary, j.experience, m.recruitType, actStr].filter(Boolean).join('　');
  // 目标岗位上下文：当前选中目标（来自履历）
  api('/profile').then((p) => {
    const cur = (p.targets || []).find((t) => t.id === p.activeTarget);
    if (cur && $('#jpMeta')) {
      const base = $('#jpMeta').textContent;
      $('#jpMeta').textContent = '目标：' + (cur.title || '（未命名）') + (base ? '　' + base : '');
    }
  }).catch(() => {});
  const jmScore = m.jdMatch ? m.jdMatch.matchRate.overall : null;
  const scoreHtml = jmScore == null
    ? '<div class="empty">该岗位没有可分析的技能文本（JD 或技能标签为空），先抓取 JD 再评估。</div>'
    : `<div class="jscore"><div><div class="jscorev">${jmScore}%</div><div class="small muted">岗位 × 履历 匹配度</div></div>
       <div class="bar" style="flex:1;height:10px"><i style="width:${jmScore}%;${jmScore >= 60 ? '' : 'background:linear-gradient(90deg,#d98510,#c0503f)'}"></i></div>
       <div class="small muted" style="max-width:220px">jd_match_v1 层级匹配率：JD 需求维度 × 你的 L1-L4 实际层级，超配不计分（与岗位池相关度同口径）</div></div>`;
  const evdOf = (s) => {
    const e = s.evidence || {};
    const parts = [];
    if (e.statement) parts.push(`<div class="evs">${esc(e.statement)}</div>`);
    if ((e.metrics || []).length) parts.push(`<div class="small muted">量化结果：${e.metrics.map(esc).join('；')}</div>`);
    if ((e.projectRefs || []).length) parts.push(`<div class="small muted">项目落点：${e.projectRefs.map(esc).join('、')}</div>`);
    if ((e.artifacts || []).length) parts.push(`<div class="small muted">可验证产出：${e.artifacts.map(esc).join('、')}</div>`);
    if (!parts.length) return '';
    return `<details class="evd"><summary>我的证据</summary>${parts.join('')}</details>`;
  };
  const matchedRows = m.matched.length ? m.matched.map((s) => `<tr>
      <td><b>${esc(s.name)}</b><div class="small muted">${esc(s.category)}</div>${evdOf(s)}</td>
      <td class="mono">${s.myScore}</td>
      <td><div class="bar"><i style="width:${Math.round((s.coverage || 0) * 100)}%"></i></div></td>
      <td class="mono">${Math.round((s.coverage || 0) * 100)}%</td></tr>`).join('')
    : '<tr><td colspan="4" class="muted">无 —— JD 未命中你的技能</td></tr>';
  const gapCards = m.gaps.length ? m.gaps.map((g) => {
    const pl = g.plan || {};
    return `<div class="gapcard ${g.level === '空白' ? 'p1' : 'p2'}">
      <h4><span>${esc(g.name)} <span class="chip ${g.level === '空白' ? 'bad' : 'mute'}">${g.level}</span>
        <span class="chip mute small">${esc(g.category)}</span></span>
        <span class="mono small">证据分 ${g.myScore}</span></h4>
      ${g.why ? `<div class="kv"><div class="k">为什么</div><div>${esc(g.why)}</div></div>` : ''}
      ${pl.focus ? `<div class="kv"><div class="k">学习重点</div><div>${esc(pl.focus)}</div></div>` : ''}
      ${pl.duration ? `<div class="kv"><div class="k">预计周期</div><div>${esc(pl.duration)}</div></div>` : ''}
      ${pl.verification ? `<div class="kv"><div class="k">验证方式</div><div>${esc(pl.verification)}</div></div>` : ''}
    </div>`;
  }).join('') : '<div class="empty">无缺口 —— 该岗位需要的技能你都有证据</div>';
  const pts = m.interviewPoints.length
    ? `<ul class="jpts">${m.interviewPoints.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>`
    : '<div class="empty">暂无</div>';
  const url = j.url || '';
  // 单岗层级匹配洞察（jd_match_v1：岗位 JD × 履历 L1-L4，与「岗位洞察」页同口径）
  const jm = m.jdMatch;
  const insightHtml = jm
    ? `${renderHardBanner(jm)}
      ${renderMatchDual(jm)}
      ${renderDims(jm, null, false)}
      ${renderCards(jm)}
      ${renderStrengths(jm)}`
    : '<div class="empty">该岗位暂无 JD 原文（或未命中词库维度），无法做层级匹配洞察；先由 Agent 抓取 JD 后再看。</div>';
  $('#jpBody').innerHTML = `
    ${scoreHtml}
    <div class="card"><h3>岗位洞察详情 <span class="tag">jd_match_v1 · 该岗位 JD 与你的履历做层级语义匹配（L1 用会 / L2 负责实现 / L3 主导设计 / L4 治理闭环）· 六色分型 + 四张行动卡</span></h3>${insightHtml}</div>
    <div class="card"><h3>匹配明细 <span class="tag">JD / 技能标签命中的技能 · 覆盖率为岗位池占比</span></h3>
      <table><thead><tr><th>技能</th><th>我的证据分</th><th>岗位池覆盖率</th><th></th></tr></thead>
      <tbody>${matchedRows}</tbody></table></div>
    <div class="card"><h3>缺陷与重点补充 <span class="tag">按覆盖率排序，越常见越优先补</span></h3>${gapCards}</div>
    <div class="card"><h3>面试注意点</h3>${pts}</div>
    <div class="card">
      <details><summary><b>JD 摘录</b><span class="small muted">${m.jd ? '共 ' + m.jd.length + ' 字 · 点击展开' : '（该岗位暂无 JD 原文）'}</span></summary>
        <pre class="jdpre">${esc(m.jd || '（暂无 JD 原文，先由 Agent 抓取再分析）')}</pre></details>
      <div class="row" style="margin-top:12px;justify-content:flex-end">
        ${url ? `<a class="btn primary" href="${esc(url)}" target="_blank" rel="noopener noreferrer">打开原岗位链接 ↗</a>` : '<span class="small muted">无原链接</span>'}
      </div>
    </div>`;
}

HOOKS.applications = () => {
  $$('[data-status]').forEach((sel) => (sel.onchange = async () => {
    await api('/applications', { method: 'PATCH', body: { id: sel.dataset.status, status: sel.value } });
    toast('状态已更新'); route();
  }));
  $$('[data-tl]').forEach((b) => (b.onclick = () => {
    const row = $(`[data-tlrow="${b.dataset.tl}"]`);
    row.style.display = row.style.display === 'none' ? '' : 'none';
  }));
  $$('[data-fb]').forEach((b) => (b.onclick = () => {
    $('#fbCompany').value = b.dataset.fb;
    $('#fbContent').focus();
    window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
  }));
  $('#saveFb').onclick = async () => {
    await api('/feedback', { method: 'POST', body: {
      applicationId: $('#fbCompany').value, type: $('#fbType').value,
      signal: $('#fbSignal').value, content: $('#fbContent').value,
    } });
    toast('反馈已记录'); route();
  };
};

HOOKS.settings = () => {
  refreshDaemon();   // 进入设置页立即刷新采集通道状态
  const cur = () => {
    const pick = (id, fb) => { const el = $('#' + id); return el && el.value ? el.value : fb; };
    return Object.assign({}, CUR_THEME || {}, {
      sideBg: pick('setSideBg', (CUR_THEME && CUR_THEME.sideBg) || '#5a5480'),
      bg: pick('setBg', (CUR_THEME && CUR_THEME.bg) || '#f4f6f8'),
      brand: pick('setBrand', (CUR_THEME && CUR_THEME.brand) || '#8b5cf6'),
    });
  };
  const save = async (theme) => api('/settings', { method: 'PUT', body: { theme } });
  $$('[data-theme-preset]').forEach((b) => (b.onclick = async () => {
    const s = await api('/settings');
    const preset = (s.presets || {})[b.dataset.themePreset];
    if (!preset) return;
    applyThemeVars(preset);
    await save(preset);
    $$('[data-theme-preset]').forEach((x) => x.classList.remove('ok'));
    b.classList.add('ok');
    toast('主题已应用并保存');
  }));
  ['setSideBg', 'setBg', 'setBrand'].forEach((id) => {
    const el = $('#' + id);
    if (el) el.oninput = () => applyThemeVars(cur());
  });
  const btnSave = $('#saveTheme');
  if (btnSave) btnSave.onclick = async () => { await save(cur()); toast('主题已保存'); };
  const btnLlm = $('#saveLlm');
  if (btnLlm) btnLlm.onclick = async () => {
    const body = {
      base_url: $('#llmBase').value.trim(),
      model: $('#llmModel').value.trim(),
      api_key: $('#llmKey').value.trim(),
    };
    const r = await api('/llm-config', { method: 'PUT', body });
    toast(r.ok ? (r.enabled ? 'LLM 已启用，下次分析时自动增强' : '已保存（未启用）') : '保存失败：' + (r.error || ''));
    if (r.ok) route();
  };
  const btnReset = $('#resetTheme');
  if (btnReset) btnReset.onclick = async () => {
    const s = await api('/settings');
    const p = (s.presets || {})['灰紫'];
    if (!p) return;
    applyThemeVars(p);
    await save(p);
    toast('已恢复默认主题');
    route();
  };
  const btnExport = $('#doExport');
  if (btnExport) btnExport.onclick = async () => {
    const r = await api('/export');
    toast(`已生成备份（${Math.round((r.bytes || 0) / 1024)} KB），开始下载…`);
    const a = document.createElement('a');
    a.href = '/api/export/download?ts=' + Date.now();
    a.download = 'boss-workbench-backup.zip';
    document.body.appendChild(a); a.click(); a.remove();
  };
  const btnImport = $('#doImport');
  if (btnImport) btnImport.onclick = async () => {
    if (!confirm('将用上次导出的备份覆盖当前数据，继续？')) return;
    const r = await api('/import', { method: 'POST', body: {} });
    toast(r.ok ? '已从备份恢复' : '恢复失败：' + (r.error || ''), !r.ok);
    if (r.ok) route();
  };
};

/* ---- 简历模板可视化编辑器（投递与反馈页 · 模板 tab） ---- */
HOOKS.tplEditor = () => {
  const tplSelect = $('#tplSelect');
  if (!tplSelect) return;   // 不在模板 tab，DOM 未渲染
  const TPL_BLOCKS = [
    { key: 'SUMMARY', title: '个人简介' },
    { key: 'SKILLS', title: '核心能力' },
    { key: 'PROJECTS', title: '核心项目经历' },
    { key: 'WORK', title: '工作经历' },
    { key: 'EDUCATION', title: '教育经历' },
    { key: 'OTHER', title: '' }   // 无 h2 标题，直接输出（证书行）
  ];
  const TPL_SAMPLE = {
    HEADER: "<header><h1>蔡长霖</h1><span class='intent'>求职意向 · Agent 系统工程师</span><div style='flex:1'></div></header><div class='contact'><span><b>138-0000-0000</b></span><span>name@example.com</span><span>杭州</span><span>8 年经验</span><span>github.com/example</span></div>",
    SUMMARY: "<p class='summary'>8 年系统研发与高并发架构经验，专注 Agent 系统工程落地，主导生产级多 Agent 系统与自研 Agent Harness 建设。</p>",
    SKILLS: "<div class='cap'><p><b>Agent 工程：</b>Agent Harness · 多 Agent 编排 · MCP · 上下文工程 · 评估校准</p><p><b>工程底座：</b>高并发性能优化 · 分布式架构 · K8s · 全闪存储</p></div>",
    PROJECTS: "<div class='work'><div class='item'><div class='top'><span class='ttl'>示例核心项目</span><span class='meta'>个人开源 · github.com/example</span></div><div class='stack'>技术栈：Agent Harness · MCP · Redis</div><ul><li>示例要点一：<b>量化结果加粗</b>，替代 70% 人工工作量。</li><li>示例要点二：性能 <b>200ms→35ms</b>，效率提升 5-10 倍。</li></ul></div></div>",
    WORK: "<div class='work'><div class='wrow'><span class='wco'>示例公司</span><span class='wrole'>高级工程师 · 远程</span><span class='wdate'>2022.01 - 2024.01</span></div><p class='desc'>示例职责描述，量化成果 <b>加粗展示</b>，支撑万人日活。</p><div class='wstack'>技术栈：TypeScript · Redis · K8s</div></div>",
    EDUCATION: "<div class='edu'><span><b>示例大学</b> · 软件工程 · 硕士</span><span class='wdate'>2015.09 - 2017.06</span></div>",
    OTHER: "<div class='other'>英语六级（CET-6）· 示例证书</div>"
  };
  let tplCfg = { name: 'resume.html', builtin: true, css: '', blocks: [] };
  const tplPreview = $('#tplPreview'), tplName = $('#tplName'), tplSave = $('#tplSave'), tplSaveAs = $('#tplSaveAs'),
        tplSetDefault = $('#tplSetDefault'), tplDelete = $('#tplDelete'), tplRestore = $('#tplRestore'),
        tplStylePanel = $('#tplStylePanel'), tplStyleTitle = $('#tplStyleTitle'),
        tplStyleJson = $('#tplStyleJson'), tplStyleApply = $('#tplStyleApply'), tplStyleHint = $('#tplStyleHint'),
        tplStyleCount = $('#tplStyleCount'), tplStyleClose = $('#tplStyleClose');
  let tplStyleKey = '';   // 当前正在编辑样式的区块
  // 每个区块关联的 CSS 选择器（标题 h2 + 正文 + 小标题 + 要点列表，编辑时整组展示）
  const TPL_SELS = {
    SUMMARY: ['h2', '.summary'],
    SKILLS: ['h2', '.cap'],
    PROJECTS: ['h2', '.item', '.top', '.ttl', '.meta', '.stack', 'ul', 'li'],
    WORK: ['h2', '.work', '.wrow', '.wco', '.wrole', '.wdate', '.desc', '.wstack', 'ul', 'li'],
    EDUCATION: ['h2', '.edu'],
    OTHER: ['.other']
  };
  function splitCss(css) {
    const rules = [];
    const re = /([^{}]+)\{([^{}]*)\}/g;
    let m;
    while ((m = re.exec(css))) rules.push({ sel: m[1].trim(), body: m[2] });
    return rules;
  }
  function propsToObj(body) {
    const obj = {};
    body.split(';').forEach((seg) => {
      const i = seg.indexOf(':');
      if (i > 0) { const k = seg.slice(0, i).trim(), v = seg.slice(i + 1).trim(); if (k) obj[k] = v; }
    });
    return obj;
  }
  function cssToJson(css) {
    const obj = {};
    for (const r of splitCss(css)) obj[r.sel] = Object.assign(obj[r.sel] || {}, propsToObj(r.body));
    return JSON.stringify(obj, null, 2);
  }
  function jsonToCss(jsonText) {
    const obj = JSON.parse(jsonText);
    const lines = [];
    for (const sel of Object.keys(obj)) {
      const props = obj[sel];
      if (typeof props !== 'object' || props === null || Array.isArray(props)) throw new Error(`规则「${sel}」的值必须是对象，如 {"color":"#000"}`);
      lines.push(`${sel}{${Object.entries(props).map(([k, v]) => `${k}:${v}`).join(';')};}`);
    }
    return lines.join('\n');
  }
  function blockRules(key) {
    const sels = TPL_SELS[key] || [];
    return splitCss(tplCfg.css).filter((r) => sels.some((s) => r.sel.split(',').some((x) => x.trim().includes(s))));
  }
  let tplStyleMode = 'block';  // block=整块区块样式 | el=区块内单个元素样式
  let tplStyleSels = [];       // el 模式下命中的选择器（完全匹配）
  function openBlockStyle(key) {
    tplStyleMode = 'block'; tplStyleSels = [];
    tplStyleKey = key;
    const b = TPL_BLOCKS.find((x) => x.key === key);
    tplStyleTitle.textContent = `区块：${b.title || '其他（证书等）'}`;
    const rules = blockRules(key);
    tplStyleJson.value = cssToJson(rules.map((r) => `${r.sel}{${r.body}}`).join('\n'));
    tplStyleCount.textContent = `${rules.length} 条规则 · 来自 ${tplCfg.name}`;
    tplStyleHint.textContent = '点击区块内某个元素可只看并改它的样式；整块规则在此，改完点「应用样式」写回';
  }
  function openElStyle(sels, hits) {
    tplStyleMode = 'el'; tplStyleSels = sels;
    tplStyleKey = '';
    tplStyleTitle.textContent = `元素：${sels.join(' / ')}`;
    const rules = splitCss(tplCfg.css).filter((r) => sels.some((s) => r.sel.split(',').some((x) => x.trim() === s)));
    tplStyleJson.value = cssToJson(rules.map((r) => `${r.sel}{${r.body}}`).join('\n'));
    const hitStr = hits && hits.length ? ` · 命中 ${hits.length + 1} 处（含共用，已全部高亮）` : '';
    tplStyleCount.textContent = `${rules.length} 条规则${hitStr}`;
    tplStyleHint.textContent = '该选择器在模板中共用处的样式会一起改，改完点「应用样式」写回';
  }
  function applyBlockStyle() {
    if (tplStyleMode === 'block' && !tplStyleKey) return;
    let edited = '';
    try { edited = jsonToCss(tplStyleJson.value); }
    catch (e) { return toast('JSON 有误：' + e.message, true); }
    const editedRules = splitCss(edited);
    const rules = splitCss(tplCfg.css);
    const sels = tplStyleMode === 'el' ? tplStyleSels : (TPL_SELS[tplStyleKey] || []);
    const match = (sel, s) => {
      const parts = sel.split(',').map((x) => x.trim());
      return tplStyleMode === 'el' ? parts.some((x) => x === s) : parts.some((x) => x.includes(s));
    };
    const idxs = rules.map((r, i) => (sels.some((s) => match(r.sel, s)) ? i : -1)).filter((i) => i >= 0);
    if (idxs.length) {
      const first = idxs[0], last = idxs[idxs.length - 1];
      rules.splice(first, last - first + 1, ...editedRules);
    } else {
      rules.push(...editedRules);
    }
    tplCfg.css = rules.map((r) => `${r.sel}{${r.body}}`).join('\n');
    preview();
    if (tplStyleMode === 'el') openElStyle(tplStyleSels); else openBlockStyle(tplStyleKey);
    toast('样式已应用，记得「保存/另存」写入模板');
  }
  function parseTemplate(src) {
    const css = (src.match(/<style>([\s\S]*?)<\/style>/) || ['', ''])[1];
    const blocks = [];
    for (const b of TPL_BLOCKS) {
      if (src.includes('{{' + b.key + '}}')) blocks.push(b.key);
    }
    blocks.sort((a, b2) => src.indexOf('{{' + a + '}}') - src.indexOf('{{' + b2 + '}}'));
    return { css, blocks };
  }
  function buildTemplate() {
    let body = '{{HEADER}}';
    for (const k of tplCfg.blocks) {
      const b = TPL_BLOCKS.find((x) => x.key === k);
      body += b.title ? `\n  <h2>${b.title}</h2>\n  {{${k}}}` : `\n  {{${k}}}`;
    }
    return `<!doctype html><html><head><meta charset="utf-8"><style>${tplCfg.css}</style></head><body><div class="page">${body}\n</div></body></html>`;
  }
  function preview() {
    const blocksHtml = tplCfg.blocks.map((k) => {
      const b = TPL_BLOCKS.find((x) => x.key === k);
      const titleHtml = b.title ? `<h2>${b.title}</h2>` : '';
      return `<section class="pv" data-key="${k}" draggable="true"><span class="pv-tag">${esc(b.title || '其他（证书等）')}</span>${titleHtml}${TPL_SAMPLE[k]}</section>`;
    }).join('\n');
    // 高度按视口剩余空间适配：内容超出时在预览区内部滚动（单滚动条，页面整体不滚动）
    fitTplHeights();
    tplPreview.srcdoc = `<!doctype html><html><head><meta charset="utf-8"><style>${tplCfg.css}
.pv{position:relative;border:1.5px dashed transparent;border-radius:4px;padding:2px 8px;margin:3px -8px;cursor:grab;transition:border-color .12s}
.pv:hover{border-color:#93c5fd}
.pv.drag{opacity:.45;border-color:#2563eb}
.pv.over{border-color:#2563eb;border-style:solid;background:rgba(37,99,235,.06)}
.pv.sel{border-color:#2563eb;border-style:solid;background:rgba(37,99,235,.05);box-shadow:0 0 0 2px rgba(37,99,235,.12)}
.pv .pv-tag{position:absolute;top:-9px;right:8px;font-size:10px;color:#2563eb;background:#fff;border:1px solid #93c5fd;border-radius:99px;padding:0 7px;line-height:16px;display:none}
.pv:hover .pv-tag{display:inline-block}
.pv .pv-rm{position:absolute;top:-9px;left:8px;width:17px;height:17px;line-height:15px;text-align:center;border-radius:50%;background:#ef4444;color:#fff;font-size:11px;cursor:pointer;display:none}
.pv:hover .pv-rm{display:block}
.el-sel{outline:2px solid #2563eb;outline-offset:1px;background:rgba(37,99,235,.08)}
.el-shared{outline:2px dashed #f59e0b;outline-offset:1px;background:rgba(255,237,213,.55)}
</style></head><body><div class="page">${blocksHtml}
</div><script>
(function(){var B=[].slice.call(document.querySelectorAll('.pv'));
B.forEach(function(b){b.addEventListener('dragstart',function(e){B.forEach(function(x){x.classList.remove('drag')});b.classList.add('drag');if(e.dataTransfer){e.dataTransfer.setData('text/plain',b.dataset.key);e.dataTransfer.effectAllowed='move'}});
b.addEventListener('dragend',function(){B.forEach(function(x){x.classList.remove('drag','over')})});
b.addEventListener('dragover',function(e){e.preventDefault();B.forEach(function(x){x.classList.remove('over')});b.classList.add('over')});
b.addEventListener('drop',function(e){e.preventDefault();var d=document.querySelector('.pv.drag');if(!d||d===b)return;var o=B.map(function(x){return x.dataset.key});o.splice(o.indexOf(d.dataset.key),1);o.splice(o.indexOf(b.dataset.key),0,d.dataset.key);parent.postMessage(JSON.stringify({t:'tpl-order',blocks:o}),'*')});
b.addEventListener('click',function(){B.forEach(function(x){x.classList.remove('sel')});b.classList.add('sel');parent.postMessage(JSON.stringify({t:'tpl-select',key:b.dataset.key}),'*')});
var rm=document.createElement('span');rm.className='pv-rm';rm.textContent='×';rm.title='从模板中移除该区块';rm.addEventListener('click',function(e){e.stopPropagation();parent.postMessage(JSON.stringify({t:'tpl-remove',key:b.dataset.key}),'*')});b.appendChild(rm)});
document.addEventListener('click',function(e){
  var t=e.target;
  if(!t||!t.classList)return;
  if(t.classList.contains('pv')||t.classList.contains('pv-tag')||t.classList.contains('pv-rm'))return;
  var sels=[],sheets=document.styleSheets;
  try{for(var i=0;i<sheets.length;i++){var rules=sheets[i].cssRules||[];for(var j=0;j<rules.length;j++){var r=rules[j];if(r.type===1&&r.selectorText&&!/(^|,)\\s*\\*|html/.test(r.selectorText)&&t.matches(r.selectorText)){var parts=r.selectorText.split(',').map(function(s){return s.trim()});for(var k=0;k<parts.length;k++){if(t.matches(parts[k])&&sels.indexOf(parts[k])<0)sels.push(parts[k]);}}}}}catch(err){}
  if(!sels.length)return;
  e.stopPropagation();
  document.querySelectorAll('.el-sel,.el-shared').forEach(function(x){x.classList.remove('el-sel','el-shared')});
  var hits=[];sels.forEach(function(s){[].slice.call(document.querySelectorAll(s)).forEach(function(el){if(el===t){el.classList.add('el-sel')}else if(hits.indexOf(el)<0){el.classList.add('el-shared');hits.push(el)}})});
  parent.postMessage(JSON.stringify({t:'tpl-el',sels:sels,hits:hits}),'*');
},true);
})();
<\/script></body></html>`;
  }
  window.addEventListener('message', (e) => {
    let d = null;
    try { d = JSON.parse(typeof e.data === 'string' ? e.data : JSON.stringify(e.data)); } catch (_) { return; }
    if (!d) return;
    if (d.t === 'tpl-order' && Array.isArray(d.blocks)) { tplCfg.blocks = d.blocks; preview(); }
    else if (d.t === 'tpl-remove' && d.key) { tplCfg.blocks = tplCfg.blocks.filter((k) => k !== d.key); preview(); }
    else if (d.t === 'tpl-select' && d.key) { openBlockStyle(d.key); }
    else if (d.t === 'tpl-el' && Array.isArray(d.sels) && d.sels.length) { openElStyle(d.sels, d.hits || []); }
  });
  async function loadTpl(name) {
    const r = await api('/resume/templates?name=' + encodeURIComponent(name)).catch(() => null);
    if (!r || !r.content) return toast('读取模板失败：' + (r && r.error || ''), true);
    tplCfg = { name, builtin: !!r.builtin, ...parseTemplate(r.content) };
    tplName.placeholder = '新模板名（无需填 .html，留空自动生成副本名）';
    tplStyleKey = '';
    tplStyleMode = 'block'; tplStyleSels = [];
    tplStyleTitle.textContent = '点击左侧预览中的区块或区块内元素查看样式';
    tplStyleJson.value = '';
    tplStyleHint.textContent = '点区块=整块样式；点区块内某个元素（如 bullet 要点）=只编辑该元素样式，共用处会一起高亮';
    tplStyleCount.textContent = '';
    preview();
  }
  tplSelect.onchange = () => loadTpl(tplSelect.value);
  tplRestore.onclick = () => { tplCfg.blocks = TPL_BLOCKS.map((b) => b.key); preview(); };
  // 字号同比例缩放：把 CSS 里所有 font-size: Npx 的 N 乘系数（0.9 / 1.1）
  const scaleFont = (factor) => {
    if (!tplCfg || !tplCfg.css) return;
    let n = 0;
    tplCfg.css = tplCfg.css.replace(/font-size\s*:\s*([\d.]+)px/gi, (m, num) => {
      n++;
      return `font-size:${(parseFloat(num) * factor).toFixed(1)}px`;
    });
    preview();
    toast(`已 ${factor > 1 ? '放大' : '缩小'} ${n} 处 font-size（×${factor}），记得「保存」写入模板`);
  };
  $('#tplFontDown').onclick = () => scaleFont(0.9);
  $('#tplFontUp').onclick = () => scaleFont(1.1);
  tplStyleApply.onclick = applyBlockStyle;
  tplStyleClose.onclick = () => {
    tplStyleKey = '';
    tplStyleMode = 'block'; tplStyleSels = [];
    tplStyleTitle.textContent = '点击左侧预览中的区块或区块内元素查看样式';
    tplStyleJson.value = '';
    tplStyleHint.textContent = '点区块=整块样式；点区块内某个元素（如 bullet 要点）=只编辑该元素样式，共用处会一起高亮';
    tplStyleCount.textContent = '';
  };
  tplSetDefault.onclick = async () => {
    const r = await api('/resume/templates', { method: 'PUT', body: { default: tplCfg.name } });
    if (r.ok) modal(`默认简历模板已设为 <b>${tplCfg.name}</b>，生成简历时将优先使用它。`);
    else modal((r.error || '设置失败'), false);
  };
  tplDelete.onclick = async () => {
    if (tplCfg.builtin) return modal('内置模板不可删除，可先「另存」为自定义模板后再删。', false);
    if (!confirm(`确定删除模板 ${tplCfg.name} 吗？此操作不可恢复。`)) return;
    let r;
    try { r = await api('/resume/templates', { method: 'DELETE', body: { name: tplCfg.name } }); }
    catch (e) { return modal((e.message || '删除失败').slice(0, 80), false); }
    if (r && r.ok) {
      const deleted = tplCfg.name;
      await loadTpl('resume.html');   // 切回内置默认模板
      const lst = await api('/resume/templates'); tplSelect.innerHTML = lst.templates.map((t) => `<option value="${esc(t.name)}" ${t.name === tplCfg.name ? 'selected' : ''}>${esc(t.name)}${t.builtin ? '（内置）' : '（自定义）'}</option>`).join('');
      modal(`模板 ${deleted} 已删除，已切回内置模板 resume.html。`);
    } else modal((r && r.error) || '删除失败', false);
  };
  // 当前样式面板的 JSON 与已应用 CSS 是否一致；不一致则先应用再保存（避免「改了没生效」）
  function currentStyleJson() {
    if (!tplStyleKey && tplStyleMode !== 'el') return null;
    const sels = tplStyleMode === 'el' ? tplStyleSels : (TPL_SELS[tplStyleKey] || []);
    const rules = splitCss(tplCfg.css).filter((r) => {
      const parts = r.sel.split(',').map((x) => x.trim());
      return sels.some((s) => (tplStyleMode === 'el' ? parts.some((x) => x === s) : parts.some((x) => x.includes(s))));
    });
    return cssToJson(rules.map((r) => `${r.sel}{${r.body}}`).join('\n'));
  }
  async function flushPendingStyle() {
    if (!tplStyleKey && tplStyleMode !== 'el') return true;
    try { jsonToCss(tplStyleJson.value); } catch (e) { toast('样式 JSON 有误：' + e.message, true); return false; }
    if (currentStyleJson() !== tplStyleJson.value) { applyBlockStyle(); toast('已先应用未保存的样式修改，再写入模板'); }
    return true;
  }
  /* 模板名归一：自动补全 .html 后缀（用户无需填写） */
  function normalizeTplName(raw) {
    let name = (raw || '').trim();
    if (!name) return '';
    if (!name.toLowerCase().endsWith('.html')) name += '.html';
    return name;
  }
  const badNameMsg = '模板名只能包含字母/数字/横线，如 myresume';
  tplSave.onclick = async () => {
    if (!(await flushPendingStyle())) return;
    // 保存 = 重命名：输入框有名字 → 用新名字保存（旧模板若是用户自定义则删除）；为空 → 覆盖当前模板
    let name = normalizeTplName(tplName.value) || tplCfg.name;
    if (!/^[\w\-]+\.html$/.test(name)) return modal(badNameMsg, false);
    const oldName = tplCfg.name;
    let r;
    try { r = await api('/resume/templates', { method: 'PUT', body: { name, content: buildTemplate() } }); }
    catch (e) { return modal((e.message || '保存失败').slice(0, 80), false); }
    if (r && r.ok) {
      if (name !== oldName) {   // 重命名：旧模板若是用户自定义则删除，避免下拉出现两份
        try { await api('/resume/templates', { method: 'DELETE', body: { name: oldName } }); } catch (_) { /* 内置模板不可删，忽略 */ }
        tplCfg.name = name; tplCfg.builtin = false;      }
      tplName.value = '';
      const lst = await api('/resume/templates'); tplSelect.innerHTML = lst.templates.map((t) => `<option value="${esc(t.name)}" ${t.name === name ? 'selected' : ''}>${esc(t.name)}${t.builtin ? '（内置）' : '（自定义）'}</option>`).join('');
      modal(name !== oldName ? `模板已重命名为 ${name}，旧模板已移除，下拉已选中它。` : `模板 ${name} 已保存。`);
    } else modal((r && r.error) || '保存失败', false);
  };
  tplSaveAs.onclick = async () => {
    if (!(await flushPendingStyle())) return;
    // 另存 = 新模板：用输入框名字（留空自动生成副本名，后缀自动补全）
    let name = normalizeTplName(tplName.value);
    if (!name) {
      const lst = await api('/resume/templates').catch(() => ({ templates: [] }));
      const names = new Set((lst.templates || []).map((t) => t.name));
      name = 'resume-copy.html';
      for (let i = 2; names.has(name); i++) name = `resume-copy${i}.html`;
      tplName.value = 'resume-copy';
    }
    if (!/^[\w\-]+\.html$/.test(name)) return modal(badNameMsg, false);
    let r;
    try { r = await api('/resume/templates', { method: 'PUT', body: { name, content: buildTemplate() } }); }
    catch (e) { return modal((e.message || '保存失败').slice(0, 80), false); }
    if (r && r.ok) {
      tplCfg.name = name; tplCfg.builtin = false; tplName.value = '';
      const lst = await api('/resume/templates'); tplSelect.innerHTML = lst.templates.map((t) => `<option value="${esc(t.name)}" ${t.name === name ? 'selected' : ''}>${esc(t.name)}${t.builtin ? '（内置）' : '（自定义）'}</option>`).join('');
      modal(`新模板 ${name} 已另存，下拉已自动选中。`);
    } else modal((r && r.error) || '保存失败', false);
  };
  // 预览区/样式面板高度按视口剩余空间适配（页面整体不滚动，内容超出各自内部滚动）
  function fitTplHeights() {
    const f = $('#tplPreview'), a = $('#tplStylePanel');
    if (!f) return;
    const top = f.getBoundingClientRect().top;
    const h = Math.max(340, Math.floor(window.innerHeight - top - 96));  // 96 = 下方控件行+说明+边距
    f.style.height = h + 'px';
    if (a) a.style.height = h + 'px';
  }
  fitTplHeights();
  window.addEventListener('resize', fitTplHeights);
  loadTpl(tplSelect.value);
};

/* ------------------------------------------------------------- bootstrap - */
async function refreshDaemon() {
  const dot = $('#bossDot');
  try {
    const d = await api('/daemon');
    let cls, tip;
    if (d.running) {
      if (d.loggedIn === false) { cls = 'warn'; tip = 'BOSS 采集：运行中 · 待登录（点此进入设置）'; }
      else { cls = 'ok'; tip = 'BOSS 采集：运行中（点此进入设置）'; }
    } else { cls = 'off'; tip = 'BOSS 采集：未运行（点此进入设置启动）'; }
    if (dot) { dot.className = 'boss-dot ' + cls; dot.title = tip; }
    const st = $('#daemonState');
    if (st) st.innerHTML = d.running
      ? (d.loggedIn === false
        ? '● 运行中 · 待登录（请到 Chrome 的 BOSS直聘 页面扫码/登录）'
        : `● 运行中${d.lastAdded != null ? `（上次 +${d.lastAdded}/~${d.lastUpdated}）` : ''}`)
      : '○ 未运行';
    const tg = $('#daemonToggle');
    if (tg) {
      tg.textContent = d.running ? '停止采集' : '启动采集';
      tg.className = d.running ? '' : 'primary';
      tg.onclick = async () => {
        const r = await api(d.running ? '/daemon/stop' : '/daemon/start', { method: 'POST', body: {} });
        toast(r.ok ? (d.running ? '已发送停止指令' : 'boss-daemon 已启动，BOSS 登录页将打开（登录后即可刷新采集）') : ('失败：' + (r.error || '')), !r.ok);
        setTimeout(refreshDaemon, d.running ? 1500 : 2500);
      };
    }
  } catch {
    if (dot) { dot.className = 'boss-dot bad'; dot.title = '服务未响应'; }
    const st = $('#daemonState');
    if (st) st.innerHTML = '✗ 服务未响应';
    const tg = $('#daemonToggle');
    if (tg) { tg.textContent = '重试'; tg.className = 'primary'; tg.onclick = () => refreshDaemon(); }
  }
}

function updateHealth(text, cls) {
  const h = $('#health');
  if (h) { h.textContent = text; h.className = 'pill ' + cls; }
  const h2 = $('#health2');
  if (h2) { h2.textContent = text; h2.className = 'pill ' + cls; }
}

(async () => {
  try { const h = await api('/health'); updateHealth('✓ 已连接', 'ok'); }
  catch { updateHealth('✗ 服务未响应', 'bad'); }
  try { const s = await api('/settings'); if (s && s.theme) applyThemeVars(s.theme); } catch (e) { /* 主题加载失败则用默认 */ }
  const dot0 = $('#bossDot');
  if (dot0) dot0.onclick = () => { location.hash = '#/settings'; };
  refreshDaemon();
  window.addEventListener('hashchange', route);
  route();
  // 概览页实时刷新：Agent / 调度器的写操作会立即反映到看板（10s 轮询）
  setInterval(async () => {
    refreshDaemon();
    const base = (location.hash.replace('#/', '').split('?')[0] || 'overview');
    if (base !== 'overview') return;
    const el = $('#view');
    if (!el) return;
    try { el.innerHTML = await overviewHtml(); } catch (e) { /* 静默：下次轮询重试 */ }
  }, 10000);
})();
