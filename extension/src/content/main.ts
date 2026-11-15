// Content script (classic-script IIFE, no React): a floating launcher plus the overlay iframe. We only ever add our own two host
// elements to the page (never read or change the site's DOM); each lives in a Shadow DOM so site CSS cannot touch it.
import { SITES, siteFor } from '../sites.ts';

const EASE = 'cubic-bezier(.23,1,.32,1)';
const Z = '2147483647';
const SHADOW: ShadowRootMode = __RP_DEV__ ? 'open' : 'closed'; // open only so browser tests can reach inside

// RP_DEV builds: <meta name="rp-test-site" content="netflix"> stands in for the hostname on http://127.0.0.1 test pages
const siteId = () => {
  const test = __RP_DEV__ ? document.querySelector<HTMLMetaElement>('meta[name="rp-test-site"]')?.content : '';
  return (test && SITES.find((s) => s.id === test)?.id) || siteFor(location.hostname)?.id || '';
};

const CSS = `
:host { all: initial }
*, *::before, *::after { box-sizing: border-box }
button { font: 600 13px/1 system-ui, -apple-system, 'Segoe UI', sans-serif; -webkit-font-smoothing: antialiased }
.launch { display: flex; align-items: center; gap: 0; height: 44px; padding: 0 13px; border-radius: 22px; border: 1px solid rgb(255 255 255 / .14); background: #1c1c1f; color: #fff; cursor: pointer;
  box-shadow: 0 8px 24px -6px rgb(0 0 0 / .6); transition: transform 160ms ${EASE}, border-color 160ms, background 160ms }
.launch:hover { background: #26262a; border-color: rgb(255 255 255 / .26) }
.launch:active { transform: scale(.97) }
.launch:focus-visible { outline: 2px solid #fff; outline-offset: 2px }
.launch svg { flex: none; width: 18px; height: 18px }
.launch span { max-width: 0; opacity: 0; overflow: hidden; white-space: nowrap; transition: max-width 200ms ${EASE}, opacity 160ms, margin 200ms ${EASE} }
.launch:hover span, .launch:focus-visible span { max-width: 90px; opacity: 1; margin-left: 8px }
.back { position: fixed; inset: 0; background: rgb(0 0 0 / .5); opacity: 0; transition: opacity 200ms ${EASE} } /* swallows clicks; wheel/touch still scroll the page behind */
.frame { position: absolute; top: 16px; left: 16px; width: clamp(420px, 50vw, 760px); height: clamp(360px, 50vh, 560px); max-width: calc(100vw - 32px); max-height: calc(100vh - 32px); border: 1px solid rgb(255 255 255 / .1); border-radius: 20px; background: #17171a; color-scheme: dark; overflow: hidden;
  opacity: 0; transform: scale(.97) translateY(6px); transform-origin: top left; transition: opacity 200ms ${EASE}, transform 200ms ${EASE};
  box-shadow: 0 1px 2px rgb(0 0 0 / .4), 0 8px 24px -4px rgb(0 0 0 / .5), 0 32px 80px -12px rgb(0 0 0 / .7) }
.back.on, .back.on .frame { opacity: 1 } .back.on .frame { transform: none }
.back.out, .back.out .frame { transition-duration: 150ms }
.err { position: absolute; top: 32px; left: 32px; display: none; max-width: min(92vw, 360px); padding: 20px; border-radius: 16px; background: #1c1c1f; color: #fff; border: 1px solid rgb(255 255 255 / .1); font: 14px/1.45 system-ui, sans-serif; text-align: center }
.err.show { display: block } .err p { margin: 0 0 14px } .err button { height: 40px; padding: 0 18px; border-radius: 20px; border: 0; background: #f5f2ea; color: #0a0a0c; cursor: pointer }
@media (max-width: 760px) { .frame { width: calc(100vw - 32px); height: 70dvh } }
@media (prefers-reduced-motion: reduce) { .launch, .launch span, .back, .frame { transition: opacity 120ms !important; transform: none !important } }
`;

const MARK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 3h12v18l-6-4-6 4z"/><path d="m10 9 4 2.5L10 14z" fill="currentColor" stroke-width="1.5"/></svg>';

function mount(tag: string, html: string, z = Z): { host: HTMLElement; root: ShadowRoot } {
  const host = document.createElement(tag);
  host.style.cssText = `all:initial!important;position:fixed!important;z-index:${z}!important;`;
  const root = host.attachShadow({ mode: SHADOW });
  root.innerHTML = `<style>${CSS}</style>${html}`;
  return { host, root };
}

function init() {
  if ((window as any).__rpInjected) return; // one guard, in our own (isolated) world: the site cannot see or fake it
  (window as any).__rpInjected = true;

  const launcher = mount('rp-launcher', `<button class="launch" type="button" aria-label="Open ReelPicks">${MARK}<span>ReelPicks</span></button>`);
  launcher.host.id = 'rp-launcher-host';
  launcher.host.style.cssText += 'right:16px!important;bottom:16px!important;';

  const motionOk = () => !matchMedia('(prefers-reduced-motion: reduce)').matches;
  let ov: { host: HTMLElement; back: HTMLElement; frame: HTMLIFrameElement; err: HTMLElement; prev: Element | null; timer: number } | null = null;
  let origin = '';
  const alive = () => { try { return !!chrome.runtime.id; } catch { return false; } }; // false once the extension was reloaded or updated

  // After an extension reload this script is orphaned: its chrome.* calls throw. Remove everything it added and stop.
  const kill = () => {
    observer.disconnect();
    for (const [t, f] of listeners) window.removeEventListener(t, f, t === 'keydown');
    if (ov) clearTimeout(ov.timer);
    ov?.host.remove(); ov = null;
    launcher.host.remove();
  };

  function open() {
    if (ov) return;
    let url: string, nonce: string;
    try {
      origin = new URL(chrome.runtime.getURL('')).origin;
      // Residual risk: code running inside a listed site can frame the overlay with its own nonce and try to trick a click; it can read no data.
      // The stronger fix is a nonce verified through the background by sender.tab.id/frameId.
      nonce = crypto.randomUUID(); // overlay.html renders in a frame only after we send this back (see overlay/main.tsx)
      url = chrome.runtime.getURL(`overlay.html?site=${siteId()}&n=${nonce}`);
    } catch { return kill(); }
    const { host, root } = mount('rp-overlay', `<div class="back"><iframe class="frame" title="ReelPicks" allow="autoplay; encrypted-media; clipboard-write"></iframe><div class="err" role="alert"><p>ReelPicks could not load on this page.</p><button type="button">Open in a new tab</button></div></div>`, String(+Z - 1)); // one below the launcher, which stays clickable as the toggle
    host.style.cssText += 'inset:0!important;';
    const back = root.querySelector<HTMLElement>('.back')!;
    const frame = root.querySelector('iframe')!;
    const err = root.querySelector<HTMLElement>('.err')!;
    back.addEventListener('mousedown', (e) => e.preventDefault()); // a click on the dim layer must not pull focus out of the iframe
    err.querySelector('button')!.onclick = () => { window.open(chrome.runtime.getURL(`overlay.html?site=${siteId()}`), '_blank', 'noopener'); close(); };
    const timer = window.setTimeout(() => err.classList.add('show'), 4000); // cleared by the overlay's rp-ready,
    frame.addEventListener('load', () => { frame.focus(); frame.contentWindow?.postMessage({ type: 'rp-init', nonce }, origin); });
    frame.src = url;
    ov = { host, back, frame, err, prev: document.activeElement, timer };
    document.documentElement.append(host);
    requestAnimationFrame(() => requestAnimationFrame(() => back.classList.add('on')));
    frame.focus();
  }

  function close() {
    if (!ov) return;
    const { host, back, prev, timer } = ov;
    ov = null;
    clearTimeout(timer);
    back.classList.remove('on');
    back.classList.add('out');
    setTimeout(() => host.remove(), motionOk() ? 150 : 0);
    if (prev === launcher.host) launcher.root.querySelector('button')!.focus({ preventScroll: true });
    else if (prev instanceof HTMLElement && prev.isConnected) prev.focus({ preventScroll: true });
  }

  launcher.root.querySelector('button')!.addEventListener('click', () => (ov ? close() : open()));

  const onMessage = (e: MessageEvent) => {
    if (!ov || e.source !== ov.frame.contentWindow || e.origin !== origin) return;
    if (e.data?.type === 'rp-close') close();
    else if (e.data?.type === 'rp-ready') { clearTimeout(ov.timer); ov.err.classList.remove('show'); } // late is fine
  };
  const onKey = (e: KeyboardEvent) => {
    if (!e.isTrusted) return; // the page's own scripts cannot drive the hotkey/Esc
    if (e.altKey && e.shiftKey && e.code === 'KeyR') { e.preventDefault(); ov ? close() : open(); }
    else if (ov && e.key === 'Escape') { e.preventDefault(); e.stopImmediatePropagation(); close(); }
  };

  // SPA sites re-render and may drop foreign nodes: keep the launcher attached, never twice. Observer + navigation events, no polling.
  const ensure = () => { if (!alive()) return kill(); if (!launcher.host.isConnected) document.documentElement.append(launcher.host); };
  const listeners: [string, (e: any) => void][] = [['message', onMessage], ['keydown', onKey], ['popstate', ensure], ['hashchange', ensure]];
  for (const [t, f] of listeners) window.addEventListener(t, f, t === 'keydown');
  const observer = new MutationObserver(ensure);
  observer.observe(document.documentElement, { childList: true });
  ensure();
}

init();
