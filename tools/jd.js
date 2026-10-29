(() => {
  const t = (s) => { const e = document.querySelector(s); return e ? e.innerText.trim() : ''; };
  return JSON.stringify({
    url: location.href,
    title: t('.name h1') || t('h1') || document.title,
    salary: t('.salary'),
    company: t('.company-info .name') || t('.sider-company .name'),
    jd: (document.querySelector('.job-detail-section') || document.querySelector('.job-detail') || document.body).innerText.slice(0, 4000),
  });
})()
