(async () => {
  const KEYWORDS = ['Agent应用工程师', 'AI Agent工程师', '大模型应用开发', 'LLM应用工程师', 'AI应用工程师'];
  const CITIES = { '杭州': '101210100', '上海': '101020100', '苏州': '101190400' };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const out = [];

  async function search(query, city, cityName) {
    const u = `/wapi/zpgeek/search/joblist.json?scene=1&query=${encodeURIComponent(query)}&city=${city}&page=1&pageSize=30`;
    try {
      const r = await fetch(u, { credentials: 'include', headers: { accept: 'application/json' } });
      const d = await r.json();
      const list = (d.zpData && d.zpData.jobList) || [];
      for (const j of list) {
        out.push({
          q: query,
          city: cityName,
          name: j.jobName,
          salary: j.salaryDesc,
          company: j.brandName,
          industry: j.brandIndustry,
          scale: j.brandScaleName,
          stage: j.brandStageName,
          area: (j.cityName || '') + (j.areaDistrict || '') + (j.businessDistrict || ''),
          exp: j.jobExperience,
          degree: j.jobDegree,
          skills: j.skills || [],
          welfare: j.welfareList || [],
          boss: (j.bossName || '') + ' ' + (j.bossTitle || ''),
          id: j.encryptJobId,
          sec: j.securityId,
          lid: j.encryptBrandId,
        });
      }
      return list.length;
    } catch (e) {
      return 'ERR ' + e.message;
    }
  }

  for (const [cityName, city] of Object.entries(CITIES)) {
    for (const kw of KEYWORDS) {
      await search(kw, city, cityName);
      await sleep(700);
    }
  }
  // remote-oriented sweep
  for (const kw of ['Agent 远程', '大模型 远程']) {
    await search(kw, '100010000', '全国');
    await sleep(700);
  }

  // dedupe by job id, keep first occurrence
  const seen = new Map();
  for (const j of out) if (!seen.has(j.id)) seen.set(j.id, j);
  return JSON.stringify({ total: out.length, unique: seen.size, jobs: [...seen.values()] });
})()
