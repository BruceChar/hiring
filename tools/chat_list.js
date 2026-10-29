(() => {
  const items = [...document.querySelectorAll('.user-list li, .user-list-content li, li.geek-friend')];
  return JSON.stringify({ url: location.href, count: items.length,
    chats: items.map(li => li.innerText.split('\n').map(s=>s.trim()).filter(Boolean)) });
})()
