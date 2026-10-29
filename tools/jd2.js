(() => {
  const t = (s) => { const e = document.querySelector(s); return e ? e.innerText.trim() : ''; };
  const btns = [...document.querySelectorAll('a,button')].filter(e => /立即沟通|继续沟通|已沟通|投递简历/.test(e.innerText||'')).map(e => ({ txt: e.innerText.trim(), cls: e.className }));
  return JSON.stringify({
    url: location.href,
    title: t('.name h1') || t('h1') || document.title,
    salary: t('.salary'),
    company: t('.company-info .name') || t('.company-info a') || t('.sider-company .name'),
    btn: btns.slice(0, 3),
    jd: (document.querySelector('.job-detail-section') || document.querySelector('.job-detail') || document.body).innerText.slice(0, 5000),
  });
})()
