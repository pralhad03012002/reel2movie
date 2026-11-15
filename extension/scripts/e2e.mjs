// Browser end-to-end test against the DEV build (RP_DEV=1 npm run build:dev). Needs puppeteer-core and Chrome.
//   PUPPETEER_DIR=<dir containing node_modules/puppeteer-core> CHROME=<chrome binary> SHOTS=<dir> node scripts/e2e.mjs
// A local http://127.0.0.1 page stands in for Netflix (<meta name="rp-test-site">); the service worker answers from
// chrome.storage.local['rp-dev'] instead of Firestore.
import { createRequire } from 'node:module';
import { createServer } from 'node:http';
import { mkdirSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const SCRATCH = '/private/tmp/claude-501/-Users-apple-Desktop-savetolist-apk/02ba1bc2-1be6-4daa-9710-6f8e80aa4e84/scratchpad';
const puppeteer = createRequire(join(process.env.PUPPETEER_DIR ?? `${SCRATCH}/rp`, 'x.js'))('puppeteer-core');
const CHROME = process.env.CHROME ?? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const SHOTS = process.env.SHOTS ?? `${SCRATCH}/ext-shots`;
const DIST = fileURLToPath(new URL('../dist', import.meta.url));
mkdirSync(SHOTS, { recursive: true });

// ---- fake data (the Movie shape of app/src/components/types.ts)
const TITLES = ['Inception', 'Parasite', 'The Dark Knight', 'Interstellar', 'Whiplash', 'Spirited Away', 'Joker', 'Dune', 'Oldboy', 'Her', 'Arrival', 'Drive',
  'Prisoners', 'Gone Girl', 'Se7en', 'Heat', 'Coco', 'Up', 'Moonlight', 'Memento', 'Snowpiercer', 'Ex Machina', 'Tenet', 'Barbie'];
const GENRES = ['Sci-Fi', 'Drama', 'Thriller', 'Animation', 'Crime'];
const SERVICES = [['Netflix'], ['Amazon Prime Video'], ['JioHotstar'], ['Netflix', 'Amazon Prime Video'], []];
// real TMDB paths so the screenshots show posters (if the network is off the images just fail to load)
const IMG = ['/ljsZTbVsrQSqZgWeep2B1QiDKuh.jpg', '/qJ2tW6WMUDux911r6m7haRef0WH.jpg', '/gEU2QniE6E77NI6lCU6MxlNBvIx.jpg', '/7IiTTgloJzvGI1TAYymCfbfl3vT.jpg', '/udDclJoHjfjb8Ekgsd4FDteOkCU.jpg', '/7fn624j5lj3xTme2SgiLCeuedmO.jpg', '/pB8BM7pdSp6B6Ih7QZ4DrQ3PmJK.jpg', '/d5iIlFn5s0ImszYzBPb8JPIfbXD.jpg', '/3bhkrj58Vtu7enYsRolD1fZdja1.jpg', '/f89U3ADr1oiB1s9GkdPOEpXUk5H.jpg'];
const mk = (i) => ({
  id: `movie_${100 + i}`, tmdbId: 100 + i, mediaType: i % 7 === 6 ? 'tv' : 'movie', title: TITLES[i], year: 1999 + i, runtimeMin: 90 + i, seasons: i % 7 === 6 ? 2 : undefined,
  overview: `${TITLES[i]} is a gripping story with a long enough overview to wrap onto a couple of lines inside the small popup panel, so the layout can be judged.`,
  tagline: i % 3 === 0 ? 'Every story has a beginning.' : undefined, rating: Math.round((6 + (i * 37 % 40) / 10) * 10) / 10,
  genres: [GENRES[i % 5], GENRES[(i + 2) % 5]], director: 'Some Director', cast: ['A. Actor', 'B. Actress', 'C. Player'].map((name) => ({ name, character: 'Lead' })),
  poster: `https://image.tmdb.org/t/p/w500${IMG[i % IMG.length]}`, backdrop: `https://image.tmdb.org/t/p/w1280${IMG[i % IMG.length]}`, trailerKey: i % 2 ? 'YoHD9XEInc0' : null,
  providers: SERVICES[i % 5].map((name) => ({ name, kind: 'stream' })).concat(i % 4 === 0 ? [{ name: 'Apple TV Store', kind: 'rent' }] : []),
  recommendations: Array.from({ length: 1 + (i % 4) }, (_, k) => ({ creator: `creator${k}`, handle: `@creator${k}`, at: new Date(Date.now() - (i + k) * 864e5).toISOString(), quote: k ? undefined : 'Watch this one.' })),
  watched: i % 6 === 5,
});
const MOVIES = TITLES.map((_, i) => mk(i));
const SETTINGS = { region: 'IN', services: ['Netflix', 'JioHotstar'], localStt: false };
const onNetflix = (m) => m.providers.some((p) => /netflix/i.test(p.name));
const NF_UNWATCHED = MOVIES.filter((m) => onNetflix(m) && !m.watched).length;
const ALL_UNWATCHED = MOVIES.filter((m) => !m.watched).length;

// ---- test page
const PAGE = `<!doctype html><meta charset=utf-8><meta name="rp-test-site" content="netflix"><title>Fake Netflix</title>
<style>body{margin:0;height:4000px;font:16px sans-serif;background:#c9c9cf;color:#111}#hostbtn{position:fixed;left:800px;top:300px;width:160px;height:60px}#hostinput{position:fixed;left:800px;top:500px}</style>
<button id=hostbtn onclick="window.__clicked=(window.__clicked||0)+1">host button</button><input id=hostinput>
<script>window.__keys=0;for(const t of ['keydown','keypress','keyup'])window.addEventListener(t,()=>window.__keys++,true)</script>`;
const server = createServer((req, res) => {
  res.setHeader('content-type', 'text/html');
  if (req.url.startsWith('/csp')) res.setHeader('Content-Security-Policy', "frame-src 'none'");
  res.end(PAGE);
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const URL_ = `http://127.0.0.1:${server.address().port}/`;

// ---- harness
let failed = 0;
const ok = (cond, msg) => { console.log(`${cond ? 'PASS' : 'FAIL'}  ${msg}`); if (!cond) failed++; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const until = async (fn, ms = 6000) => { const t = Date.now(); while (Date.now() - t < ms) { try { const v = await fn(); if (v) return v; } catch { /* retry */ } await sleep(60); } return false; };

// Chrome 137+ ignores --load-extension, so the unpacked extension is loaded over CDP (Extensions.loadUnpacked) instead.
const browser = await puppeteer.launch({
  executablePath: CHROME, headless: 'new', pipe: true, enableExtensions: true, ignoreDefaultArgs: ['--disable-extensions'],
  userDataDir: mkdtempSync(join(tmpdir(), 'rp-e2e-')),
  args: ['--enable-unsafe-extension-debugging', '--no-first-run', '--no-default-browser-check', '--autoplay-policy=no-user-gesture-required'],
});
await (await browser.target().createCDPSession()).send('Extensions.loadUnpacked', { path: DIST });
const errors = [];
const watch = (page) => {
  page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));
  page.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource|ERR_/.test(m.text())) errors.push(`console: ${m.text()}`); });
};
try {
  const swTarget = await browser.waitForTarget((t) => t.type() === 'service_worker' && t.url().endsWith('background.js'));
  const sw = await swTarget.worker();
  const EXT = new URL(swTarget.url()).host;
  const seed = (extra = {}) => sw.evaluate((d) => chrome.storage.local.set({ 'rp-dev': d }), { connected: true, movies: MOVIES, settings: SETTINGS, ...extra });
  await seed();

  const page = await browser.newPage();
  watch(page);
  await page.setViewport({ width: 1280, height: 800 });
  await page.goto(URL_);

  // -- launcher: once, survives DOM wipes
  const hosts = () => page.evaluate(() => document.querySelectorAll('rp-launcher').length);
  ok(await until(async () => (await hosts()) === 1), 'launcher appears once');
  await page.evaluate(() => { document.body.innerHTML = ''; document.getElementById('rp-launcher-host').remove(); });
  ok(await until(async () => (await hosts()) === 1), 'launcher re-attached after the site wiped the DOM and removed it');
  await sleep(1700);
  ok((await hosts()) === 1, 'still exactly one launcher after waiting (observer only, no polling)');
  await page.goto(URL_);
  await until(async () => (await hosts()) === 1);

  const launcherBox = () => page.evaluate(() => { const r = document.querySelector('rp-launcher').shadowRoot.querySelector('button').getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; });
  const isOpen = () => page.evaluate(() => !!document.querySelector('rp-overlay'));
  const frame = () => page.frames().find((f) => f.url().includes('overlay.html'));
  const waitBrowse = async () => { const f = await until(frame); await f.waitForSelector('.bs-root', { timeout: 8000 }); return f; };
  const hotkey = async () => { await page.keyboard.down('Alt'); await page.keyboard.down('Shift'); await page.keyboard.press('KeyR'); await page.keyboard.up('Shift'); await page.keyboard.up('Alt'); };

  // -- open via launcher click, close via X
  const b = await launcherBox();
  await page.mouse.click(b.x, b.y);
  ok(await until(isOpen), 'overlay opens from the launcher button');
  let f = await waitBrowse();
  ok(await f.evaluate(() => !!document.querySelector('.bs-close')), 'close (X) button is shown instead of back');
  const src = await page.evaluate(() => document.querySelector('rp-overlay').shadowRoot.querySelector('iframe').src);
  ok(/overlay\.html\?site=netflix&n=[0-9a-f-]{36}$/.test(src), `iframe src carries the site id and a nonce (${src.split('/').pop().slice(0, 40)})`);
  await sleep(300);
  await page.screenshot({ path: `${SHOTS}/1280-browse.png` });
  await f.click('.bs-close');
  ok(await until(async () => !(await isOpen()), 2000), 'overlay closes via the X button');

  // -- popup geometry + scroll + click-through behaviour
  await hotkey();
  ok(await until(isOpen), 'overlay opens via Alt+Shift+R');
  f = await waitBrowse();
  const r = await page.evaluate(() => { const b = document.querySelector('rp-overlay').shadowRoot.querySelector('iframe'); return { x: b.offsetLeft, y: b.offsetTop, w: b.offsetWidth, h: b.offsetHeight }; });
  ok(r.x === 16 && r.y === 16 && r.w === 640 && r.h === 400, `popup is top-left, 16px margin, clamp(420,50vw,760) x clamp(360,50vh,560): ${JSON.stringify(r)}`);
  for (const [w, h, ew, eh] of [[1366, 768, 683, 384], [900, 700, 450, 360], [1920, 1080, 760, 540], [390, 844, 358, 591], [761, 600, 420, 360]]) {
    await page.setViewport({ width: w, height: h });
    await sleep(250);
    const g = await page.evaluate(() => { const b = document.querySelector('rp-overlay').shadowRoot.querySelector('iframe'); return { w: b.offsetWidth, h: b.offsetHeight }; });
    ok(Math.abs(g.w - ew) <= 1 && Math.abs(g.h - eh) <= 1, `popup at ${w}x${h} is ${ew}x${eh} (got ${g.w}x${g.h})`);
    if (w === 1366 || w === 900) await page.screenshot({ path: `${SHOTS}/${w}-browse.png` });
  }
  await page.setViewport({ width: 1280, height: 800 });
  await sleep(250);
  ok(await page.evaluate(() => getComputedStyle(document.documentElement).overflow !== 'hidden' && getComputedStyle(document.body).overflow !== 'hidden'), 'page scroll is not locked');
  const y0 = await page.evaluate(() => scrollY);
  await page.mouse.move(900, 600);
  await page.mouse.wheel({ deltaY: 500 });
  ok(await until(() => page.evaluate((y) => scrollY > y, y0), 2000), 'wheel over the dim area scrolls the host page');
  await page.evaluate(() => scrollTo(0, 0));
  await page.mouse.click(880, 330);
  ok((await page.evaluate(() => window.__clicked ?? 0)) === 0, 'click on a host button under the dim layer does not fire');
  await sleep(200);
  ok(await isOpen(), 'overlay stays open after clicking the dim area');
  ok(await page.evaluate(() => document.querySelector('rp-overlay').shadowRoot.activeElement?.tagName === 'IFRAME' || document.activeElement?.tagName === 'RP-OVERLAY'), 'keyboard focus is inside the overlay iframe');

  // -- keyboard isolation: typing in the overlay never reaches the site's key handlers
  await page.evaluate(() => { window.__keys = 0; });
  await f.type('.bs-search input', 'inc');
  ok((await page.evaluate(() => window.__keys)) === 0, 'typing in the overlay fires no key events on the host page');
  await f.click('.bs-x');

  // -- Esc in an empty search box only leaves the box
  await f.click('.bs-search input');
  await page.keyboard.press('Escape');
  await sleep(250);
  ok((await isOpen()) && (await f.evaluate(() => document.activeElement?.tagName !== 'INPUT')), 'Esc in an empty search box blurs it and keeps the overlay open');

  // -- default On Netflix filter, then All
  const counts = () => f.evaluate(() => [...document.querySelectorAll('.bs-tab-n')].map((e) => +e.textContent));
  ok(await f.evaluate(() => document.querySelector('.ext-chip[aria-pressed="true"]')?.textContent.startsWith('On Netflix')), '"On Netflix" chip is on by default');
  ok((await counts())[0] === NF_UNWATCHED, `On Netflix: ${NF_UNWATCHED} unwatched (got ${(await counts())[0]})`);
  await f.evaluate(() => [...document.querySelectorAll('.ext-chip')].find((c) => c.textContent.startsWith('All my picks')).click());
  ok(await until(async () => (await counts())[0] === ALL_UNWATCHED), `All my picks widens the list to ${ALL_UNWATCHED}`);
  await f.evaluate(() => [...document.querySelectorAll('.ext-chip')].find((c) => c.textContent.startsWith('On ')).click());
  await until(async () => (await counts())[0] === NF_UNWATCHED);

  // -- search, genre dropdown, sort
  await f.type('.bs-search input', 'inception');
  ok(await until(() => f.evaluate(() => document.querySelectorAll('.bs-grid .bs-card').length === 1)), 'search "inception" finds one film');
  await f.click('.bs-x');
  await f.click('.bs-genre');
  await f.waitForSelector('[aria-label="Choose a genre"]');
  await f.evaluate(() => [...document.querySelectorAll('.bs-pop-left label')].find((l) => l.textContent.startsWith('Thriller')).click());
  ok(await until(() => f.evaluate(() => document.querySelector('.bs-gtitle').textContent === 'Thriller')), 'genre dropdown switches to Thriller');
  await f.evaluate(() => document.querySelector('.bs-trigger:not(.bs-genre)').click());
  await f.waitForSelector('[aria-label="Sort and filter"]');
  await f.evaluate(() => [...document.querySelectorAll('[aria-label="Sort and filter"] label')].find((l) => l.textContent === 'Highest rated').click());
  ok(await f.evaluate(() => document.querySelector('.bs-trigger:not(.bs-genre) .bs-trigger-label').textContent === 'Highest rated'), 'sort menu applies');
  await page.keyboard.press('Escape');
  await sleep(250);
  ok(await isOpen(), 'Esc closes the open popover first, not the overlay');
  await f.evaluate(() => [...document.querySelectorAll('.bs-trigger')][0].click()); // reopen genres to reset to All
  await f.waitForSelector('[aria-label="Choose a genre"]');
  await f.evaluate(() => [...document.querySelectorAll('.bs-pop-left label')][0].click());
  await sleep(300);

  // -- details: Watch now URL and target, watched toggle (optimistic + rollback), trailer
  await f.click('.bs-card');
  await f.waitForSelector('[aria-modal="true"]');
  const watch1 = await f.evaluate(() => { const a = [...document.querySelectorAll('[aria-modal="true"] a')].find((x) => /Watch now/.test(x.textContent)); return { href: a.href, target: a.target }; });
  ok(watch1.href.startsWith('https://www.netflix.com/search?q=') && watch1.target === '_top', `Watch now on a Netflix title -> ${watch1.href} target=${watch1.target}`);
  await sleep(1200);
  await page.screenshot({ path: `${SHOTS}/1280-detail.png` });
  // YouTube refuses to embed inside chrome-extension:// pages (player error 153, verified in an earlier run), so the overlay uses a plain link
  ok(!(await f.$('iframe[title$="trailer"]')) && !f.childFrames().some((c) => /youtube/.test(c.url())), 'no YouTube player is embedded (it refuses extension pages with error 153)');
  ok(await f.evaluate(() => { const a = [...document.querySelectorAll('[aria-modal="true"] a')].find((x) => /Watch trailer/.test(x.textContent)); return !!a && a.href.startsWith('https://www.youtube.com/watch?v=') && a.target === '_blank'; }), 'details show a "Watch trailer" link instead');
  const pressed = () => f.evaluate(() => document.querySelector('[aria-modal="true"] button[aria-pressed]').getAttribute('aria-pressed'));
  await f.click('[aria-modal="true"] button[aria-pressed]');
  ok((await pressed()) === 'true', 'Mark as watched flips optimistically');
  await sleep(300);
  ok((await sw.evaluate(async () => (await chrome.storage.local.get('rp-dev'))['rp-dev'].movies.filter((m) => m.watched).length)) === MOVIES.filter((m) => m.watched).length + 1, 'setWatched reached the background');
  await sw.evaluate(async () => { const d = (await chrome.storage.local.get('rp-dev'))['rp-dev']; d.failWrites = true; await chrome.storage.local.set({ 'rp-dev': d }); });
  await f.click('[aria-modal="true"] button[aria-pressed]');
  ok(await until(async () => (await pressed()) === 'true' && (await f.evaluate(() => !!document.querySelector('[role=status]')))), 'failed write rolls back and shows a message');
  await page.keyboard.press('Escape');
  ok(await until(() => f.evaluate(() => !document.querySelector('[aria-modal="true"]'))), 'Esc closes the details view only');
  ok(await isOpen(), 'overlay still open after closing details');
  await sw.evaluate(async () => { const d = (await chrome.storage.local.get('rp-dev'))['rp-dev']; d.failWrites = false; await chrome.storage.local.set({ 'rp-dev': d }); });

  // a title that is not on Netflix opens in a new tab
  await f.evaluate(() => [...document.querySelectorAll('.ext-chip')].find((c) => c.textContent.startsWith('All my picks')).click());
  await sleep(400);
  await f.type('.bs-search input', 'Parasite');
  await f.waitForSelector('.bs-grid .bs-card');
  await f.click('.bs-grid .bs-card');
  await f.waitForSelector('[aria-modal="true"]');
  const watch2 = await f.evaluate(() => { const a = [...document.querySelectorAll('[aria-modal="true"] a')].find((x) => /Watch now/.test(x.textContent)); return { href: a.href, target: a.target }; });
  ok(!watch2.href.includes('netflix.com') && watch2.target === '_blank', `Watch now on another service -> ${watch2.href.slice(0, 50)} target=${watch2.target}`);
  await page.keyboard.press('Escape');
  await sleep(400);

  // -- Esc and focus restore
  await page.keyboard.press('Escape');
  await f.click('.bs-x').catch(() => {});
  await page.keyboard.press('Escape');
  ok(await until(async () => !(await isOpen()), 2000), 'Esc closes the overlay');
  await page.focus('#hostinput');
  await hotkey();
  await waitBrowse();
  await hotkey();
  await until(async () => !(await isOpen()), 2000);
  ok(await page.evaluate(() => document.activeElement?.id === 'hostinput'), 'focus returns to the previously focused element on close');
  const b2 = await launcherBox();
  await page.mouse.click(b2.x, b2.y);
  await waitBrowse();
  await page.mouse.click(b2.x, b2.y);
  ok(await until(async () => !(await isOpen()), 2000), 'launcher button toggles the overlay closed');
  ok(await page.evaluate(() => document.documentElement.style.overflow === '' && document.body.style.overflow === ''), 'page overflow styles untouched');

  // -- viewports: 390x844 and 1920x1080
  await page.setViewport({ width: 390, height: 844, isMobile: false });
  await hotkey(); f = await waitBrowse(); await sleep(700);
  await page.screenshot({ path: `${SHOTS}/390-browse.png` });
  await f.click('.bs-card'); await f.waitForSelector('[aria-modal="true"]'); await sleep(900);
  await page.screenshot({ path: `${SHOTS}/390-detail.png` });
  await page.keyboard.press('Escape'); await sleep(500); await page.keyboard.press('Escape');
  await until(async () => !(await isOpen()), 2000);
  await page.setViewport({ width: 1920, height: 1080 });
  await hotkey(); f = await waitBrowse(); await sleep(700);
  await page.screenshot({ path: `${SHOTS}/1920-browse.png` });
  await page.keyboard.press('Escape'); await until(async () => !(await isOpen()), 2000);
  await page.setViewport({ width: 1280, height: 800 });

  // -- a11y and layout details at the popup size
  await hotkey(); f = await waitBrowse(); await sleep(400);
  ok(await f.evaluate(() => /^Sort and filter, /.test([...document.querySelectorAll('.bs-trigger:not(.bs-genre)')][0]?.getAttribute('aria-label') ?? '')), 'sort button has an accessible name including the current sort');
  ok(await f.evaluate(() => !!document.querySelector('.ext-div')), 'a divider separates the tabs from the site chips');
  const hit = await f.evaluate(() => ['.ext-chip', '.ext-icon', '.ext-acct', '.bs-trigger:not(.bs-genre)', '.bs-close'].map((q) => { const el = document.querySelector(q); const r = el.getBoundingClientRect(); const b = getComputedStyle(el, '::before'); return [q, Math.round(r.height + (parseFloat(b.top) < 0 ? -2 * parseFloat(b.top) : 0))]; }));
  ok(hit.every(([, h]) => h >= 40), `hit areas are 40px or more tall: ${JSON.stringify(hit)}`);
  await page.keyboard.press('Escape'); await until(async () => !(await isOpen()), 2000);

  // -- the overlay refuses to render when framed without the nonce handshake (invisible-frame clickjacking)
  const probe = (q) => page.evaluate((url) => new Promise((res) => {
    const fr = document.createElement('iframe'); fr.id = 'probe'; fr.src = url; document.body.append(fr);
    fr.addEventListener('load', () => res(true));
  }), `chrome-extension://${EXT}/overlay.html?${q}`);
  await probe('site=netflix&n=abc');
  await sleep(800);
  const pf = () => page.frames().find((x) => x.url().includes('n=abc'));
  ok((await pf().evaluate(() => document.getElementById('root').childElementCount)) === 0, 'a page that frames overlay.html gets an empty page (no init message)');
  await page.evaluate(() => document.getElementById('probe').contentWindow.postMessage({ type: 'rp-init', nonce: 'wrong' }, '*'));
  await sleep(400);
  ok((await pf().evaluate(() => document.getElementById('root').childElementCount)) === 0, 'a wrong nonce does not unlock it');
  await page.evaluate(() => document.getElementById('probe').contentWindow.postMessage({ type: 'rp-init', nonce: 'abc' }, '*'));
  ok(await until(() => pf().evaluate(() => document.getElementById('root').childElementCount > 0)), 'the right nonce from a listed-site origin unlocks it (in dev, 127.0.0.1 counts as a site)');
  await page.evaluate(() => document.getElementById('probe').remove());
  const top = await browser.newPage();
  await top.goto(`chrome-extension://${EXT}/overlay.html?site=netflix`);
  ok(await until(() => top.evaluate(() => !!document.querySelector('.bs-root'))), 'overlay.html in its own tab (the open-in-new-tab fallback) renders without a handshake');
  await top.close();

  // -- stale-while-revalidate: cached list at once, quiet refresh swaps it in place, user state kept
  const FRESH = MOVIES.map((m) => (m.title === 'Inception' ? { ...m, title: 'Inception Reborn' } : m));
  await seed({ stale: true, fresh: FRESH, delay: 1500 });
  await hotkey(); f = await waitBrowse();
  await f.type('.bs-search input', 'inc');
  ok(await until(() => f.evaluate(() => [...document.querySelectorAll('.bs-card')].some((c) => /^Inception,/.test(c.getAttribute('aria-label') ?? '')))), 'stale reply shows the cached list at once');
  let skel = false;
  const poll = setInterval(async () => { if (await f.evaluate(() => !!document.querySelector('[aria-busy="true"]')).catch(() => false)) skel = true; }, 40);
  ok(await until(() => f.evaluate(() => [...document.querySelectorAll('.bs-card')].some((c) => /^Inception Reborn,/.test(c.getAttribute('aria-label') ?? ''))), 6000), 'the fresh list swaps in after the background refresh');
  clearInterval(poll);
  ok(!skel && (await f.evaluate(() => document.querySelector('.bs-search input').value)) === 'inc', 'the swap keeps the search text and never shows the skeleton');
  await hotkey();
  ok(await until(async () => !(await isOpen()), 2000), 'overlay closed again');

  // -- offline: the quiet refresh comes back stale, so a dismissable notice with Retry shows and the list stays
  await seed({ stale: true, offline: true });
  await hotkey(); f = await waitBrowse();
  ok(await until(() => f.evaluate(() => /Offline: showing your saved list/.test(document.querySelector('[role=status]')?.textContent ?? ''))), 'offline notice shows');
  ok(await f.evaluate(() => !!document.querySelector('.bs-card') && !!document.querySelector('[role=status] button')), 'the list stays visible and the notice has Retry');
  await f.evaluate(() => document.querySelector('[role=status] button[aria-label=Dismiss]').click());
  ok(await until(() => f.evaluate(() => !document.querySelector('[role=status]'))), 'notice can be dismissed');
  await hotkey();
  ok(await until(async () => !(await isOpen()), 2000), 'overlay closed again');

  // -- notConnected on ANY reply, and a focus re-check, both land on the connect screen
  await seed();
  await hotkey(); f = await waitBrowse(); await sleep(700);
  await f.click('.bs-card'); await f.waitForSelector('[aria-modal="true"]'); await sleep(500);
  await sw.evaluate(async () => { const d = (await chrome.storage.local.get('rp-dev'))['rp-dev']; await chrome.storage.local.set({ 'rp-dev': { ...d, connected: false } }); });
  await f.evaluate(() => document.querySelector('[aria-modal="true"] button[aria-pressed]').click());
  ok(await until(() => f.evaluate(() => document.body.innerText.includes('Connect your ReelPicks account'))), 'a notConnected reply to setWatched switches to the connect screen');
  await seed();
  await f.evaluate(() => window.dispatchEvent(new Event('focus')));
  ok(await until(() => f.evaluate(() => !!document.querySelector('.bs-root'))), 'focus re-check: connected again brings the list back');
  await sw.evaluate(async () => { const d = (await chrome.storage.local.get('rp-dev'))['rp-dev']; await chrome.storage.local.set({ 'rp-dev': { ...d, connected: false } }); });
  await f.evaluate(() => window.dispatchEvent(new Event('focus')));
  ok(await until(() => f.evaluate(() => document.body.innerText.includes('Connect your ReelPicks account'))), 'focus re-check notices a disconnect made elsewhere');
  await seed();
  await page.keyboard.press('Escape'); await until(async () => !(await isOpen()), 2000);

  // -- strict page CSP (frame-src 'none'): the extension's own iframe is exempt from the page CSP; if it were not, the fallback must show
  const csp = await browser.newPage();
  watch(csp);
  await csp.setViewport({ width: 1280, height: 800 });
  await csp.goto(`${URL_}csp`);
  await until(() => csp.evaluate(() => !!document.querySelector('rp-launcher')));
  await csp.keyboard.down('Alt'); await csp.keyboard.down('Shift'); await csp.keyboard.press('KeyR'); await csp.keyboard.up('Shift'); await csp.keyboard.up('Alt');
  const cspFrame = () => csp.frames().find((x) => x.url().includes('overlay.html'));
  const loaded = await until(async () => (await cspFrame()?.evaluate(() => !!document.querySelector('.bs-root'))), 8000);
  const fallback = () => csp.evaluate(() => document.querySelector('rp-overlay')?.shadowRoot.querySelector('.err')?.classList.contains('show'));
  if (loaded) {
    await sleep(4500);
    ok(!(await fallback()), 'INFO strict CSP: the overlay iframe LOADS under frame-src none (exempt), and the fallback stays hidden after the 4 s timer');
  } else ok(await until(fallback, 3000), 'INFO strict CSP: the overlay iframe is BLOCKED under frame-src none; the fallback is shown');
  console.log(`INFO  strict-CSP result: iframe ${loaded ? 'loaded' : 'blocked'}`);
  await csp.screenshot({ path: `${SHOTS}/csp.png` });
  await csp.close();
  await page.bringToFront();

  // -- states
  const state = async (extra, text, shot) => {
    await seed(extra);
    await hotkey();
    const fr = await until(frame);
    const got = await until(() => fr.evaluate((t) => document.body.innerText.includes(t), text), 6000);
    await sleep(350);
    if (shot) await page.screenshot({ path: `${SHOTS}/${shot}.png` });
    await page.keyboard.press('Escape');
    await until(async () => !(await isOpen()), 2000);
    return got;
  };
  ok(await state({ connected: false }, 'Connect your ReelPicks account', '1280-not-connected'), 'not-connected state renders');
  ok(await state({ movies: [] }, 'No picks yet', '1280-empty'), 'empty-list state renders');
  ok(await state({ movies: MOVIES.filter((m) => !onNetflix(m)) }, 'Nothing on Netflix yet', '1280-nothing-on-site'), '"Nothing on Netflix yet" state renders');
  ok(await state({ error: 'Firestore request failed (503)' }, 'Could not load your picks', '1280-error'), 'error state renders with Retry');
  await seed();

  // -- connect page
  const cp = await browser.newPage();
  watch(cp);
  await cp.setViewport({ width: 1280, height: 800 });
  await sw.evaluate(async () => { const d = (await chrome.storage.local.get('rp-dev'))['rp-dev']; await chrome.storage.local.set({ 'rp-dev': { ...d, connected: false } }); });
  await cp.goto(`chrome-extension://${EXT}/connect.html`);
  ok(await until(() => cp.evaluate((id) => [...document.querySelectorAll('a')].some((a) => a.href === `https://reelpicks-32e42.web.app/?connect=${id}` && a.target === '_blank'), EXT)), 'connect page offers the web app connect link');
  await cp.screenshot({ path: `${SHOTS}/connect-off.png` });
  await seed();
  ok(await until(() => cp.evaluate(() => document.body.innerText.includes('Connected as dev@example.com')), 5000), 'connect page polls and flips to Connected');
  await cp.screenshot({ path: `${SHOTS}/connect-on.png` });

  ok(errors.length === 0, `no console errors in the page or frames${errors.length ? `: ${errors.slice(0, 5).join(' | ')}` : ''}`);
} catch (e) {
  failed++;
  console.log('FAIL  script error:', e?.stack ?? e);
} finally {
  await browser.close();
  server.close();
}
console.log(failed ? `\n${failed} FAILED` : '\nALL PASSED');
process.exit(failed ? 1 : 0);
