(async function () {
  const key = 'bookkeeping_access_granted';
  if (sessionStorage.getItem(key) === '1') return;
  for (;;) {
    const code = window.prompt('请输入访问暗号');
    if (code === null) { document.body.innerHTML = '<p style="padding:40px;text-align:center">需要输入正确暗号才能继续</p>'; return; }
    try {
      const r = await fetch('/api/access/verify', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({code})});
      const result = await r.json();
      if (result.ok) { sessionStorage.setItem(key, '1'); return; }
    } catch (e) {}
    window.alert('暗号错误，请重试');
  }
})();
