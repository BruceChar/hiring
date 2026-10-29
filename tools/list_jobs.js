(() => {
  const cards = [...document.querySelectorAll('.job-card-wrap, li.job-card-wrapper')];
  const out = cards.map((c) => {
    const a = c.querySelector('a[href*="job_detail"]');
    const txt = (s) => { const e = c.querySelector(s); return e ? e.innerText.trim().replace(/\n+/g, ' ') : ''; };
    return {
      name: txt('.job-name') || txt('.job-title'),
      area: txt('.job-area'),
      salary: txt('.salary'),
      company: txt('.company-name') || txt('.company-info .name'),
      tags: [...c.querySelectorAll('.tag-list li')].map((t) => t.innerText.trim()).join('/'),
      href: a ? a.getAttribute('href') : '',
    };
  });
  return JSON.stringify({ url: location.href, city: (document.querySelector('.city-label, .cur-city') || {}).innerText || '', count: out.length, jobs: out });
})()
