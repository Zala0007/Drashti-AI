// Apply the saved preference before styles paint; this also respects a strict CSP.
(() => {
  let theme = window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  try {
    const saved = localStorage.getItem('drishti-theme');
    if (saved === 'dark' || saved === 'light') theme = saved;
  } catch { /* The system preference works when storage is unavailable. */ }
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#101919' : '#f5f6f3');
})();
