/* Cinematic still + projected 3D particle field. No remote runtime dependencies. */
(function () {
  'use strict';
  const hero = document.getElementById('arenaHero');
  if (!hero) return;
  const canvas = hero.querySelector('canvas');
  const toggle = hero.querySelector('.arena-toggle');
  const hint = hero.querySelector('.arena-hint');
  const ctx = canvas.getContext('2d');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const coarse = matchMedia('(pointer: coarse)');
  let width = 0, height = 0, targetX = 0, targetY = 0, x = 0, y = 0;
  let visible = true, frame = 0, previous = 0, elapsed = 0, manualPause = false;
  let particles = [];
  const available = () => !!ctx && !reduced.matches && !coarse.matches;
  const enabled = () => available() && !manualPause && visible && !document.hidden;
  function updateLabel() {
    const active = available() && !manualPause;
    toggle.hidden = !available();
    toggle.textContent = active ? '暂停动效 Ⅱ' : '开启动效 ▶';
    toggle.setAttribute('aria-pressed', String(active));
    hint.hidden = !available();
  }
  function resize() {
    width = hero.clientWidth; height = hero.clientHeight;
    const dpr = Math.min(devicePixelRatio || 1, 1.5);
    canvas.width = Math.round(width * dpr); canvas.height = Math.round(height * dpr);
    if (ctx) ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const count = width < 900 ? 95 : 180;
    particles = Array.from({ length: count }, (_, i) => ({
      a: Math.random() * Math.PI * 2, r: .16 + Math.random() * .37,
      z: Math.random() * 1.1 + .55, speed: .04 + Math.random() * .11,
      size: .3 + Math.random() * 1.3, offset: Math.random() * 8,
      color: i % 7 === 0 ? '239,101,119' : i % 3 === 0 ? '112,177,247' : '208,223,244'
    }));
    if (!enabled() && ctx) ctx.clearRect(0, 0, width, height);
  }
  function draw(now) {
    frame = 0;
    if (!enabled()) { previous = 0; return; }
    const dt = previous ? Math.min((now - previous) / 1000, .05) : 1 / 60;
    previous = now; elapsed += dt;
    const ease = 1 - Math.exp(-dt * 5);
    x += (targetX - x) * ease; y += (targetY - y) * ease;
    hero.style.setProperty('--art-x', (x * 11).toFixed(2) + 'px');
    hero.style.setProperty('--art-y', (y * 7).toFixed(2) + 'px');
    hero.dataset.motion = 'running';
    ctx.clearRect(0, 0, width, height);
    for (const p of particles) {
      const angle = p.a + elapsed * p.speed;
      const z = p.z + Math.sin(angle) * .28;
      const perspective = 1 / z;
      const px = width * .73 + Math.cos(angle) * width * p.r * .55 * perspective + x * 18 * perspective;
      const py = height * .49 + Math.sin(angle * 1.4 + p.offset) * height * .39 * perspective + y * 12 * perspective;
      const alpha = Math.min(.65, Math.max(0, (px / width - .35) * .75)) * (.5 + .5 / z);
      ctx.beginPath(); ctx.arc(px, py, p.size * perspective, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(' + p.color + ',' + alpha.toFixed(3) + ')'; ctx.fill();
    }
    frame = requestAnimationFrame(draw);
  }
  function sync() {
    updateLabel();
    if (enabled()) { if (!frame) frame = requestAnimationFrame(draw); }
    else {
      cancelAnimationFrame(frame); frame = 0; previous = 0;
      hero.dataset.motion = 'paused';
      if (!available()) {
        hero.style.setProperty('--art-x', '0px'); hero.style.setProperty('--art-y', '0px');
        if (ctx) ctx.clearRect(0, 0, width, height);
      }
    }
  }
  hero.addEventListener('pointermove', e => {
    if (!enabled()) return;
    const box = hero.getBoundingClientRect();
    targetX = ((e.clientX - box.left) / box.width - .5) * 2;
    targetY = ((e.clientY - box.top) / box.height - .5) * 2;
  }, { passive: true });
  hero.addEventListener('pointerleave', () => { targetX = targetY = 0; });
  toggle.addEventListener('click', () => { manualPause = !manualPause; sync(); });
  document.addEventListener('visibilitychange', sync);
  reduced.addEventListener('change', sync); coarse.addEventListener('change', sync);
  new ResizeObserver(resize).observe(hero);
  new IntersectionObserver(entries => { visible = entries[0].isIntersecting; sync(); }, { threshold: 0 }).observe(hero);
  resize(); sync();
})();
