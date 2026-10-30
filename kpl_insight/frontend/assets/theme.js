/* Runs before styles and modules: restore the selected frontend without a flash. */
(function () {
  'use strict';
  var root = document.documentElement;
  var requested = new URLSearchParams(location.search).get('theme');
  var theme = 'light';
  try { theme = localStorage.getItem('kpl-site-theme') === 'dark' ? 'dark' : 'light'; } catch (_) {}
  if (requested === 'dark' || requested === 'light') {
    theme = requested;
    try { localStorage.setItem('kpl-site-theme', theme); } catch (_) {}
  }
  root.classList.toggle('light-site', theme === 'light');
  root.classList.toggle('dark-site', theme === 'dark');
  root.dataset.theme = theme;

  document.addEventListener('DOMContentLoaded', function () {
    var header = document.querySelector('#siteHeader .topbar-in');
    if (!header) return;
    var button = document.createElement('button');
    var next = theme === 'light' ? 'dark' : 'light';
    var label = next === 'dark' ? '深色版' : '浅色版';
    button.className = 'theme-switch';
    button.type = 'button';
    button.textContent = (next === 'dark' ? '☾ ' : '☀ ') + label;
    button.setAttribute('aria-label', '切换到' + label);
    button.title = '当前为' + (theme === 'light' ? '浅色版' : '深色版') + '，点击切换';
    button.addEventListener('click', function () {
      try { localStorage.setItem('kpl-site-theme', next); } catch (_) {}
      var url = new URL(location.href);
      url.searchParams.set('theme', next);
      // Reload releases the old WebGL context and initializes only the selected frontend.
      location.replace(url.href);
    });
    header.insertBefore(button, header.querySelector('.nav-toggle'));
  });
})();
