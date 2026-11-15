import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '@app/components/tokens.css';
import './index.css';
import { Overlay } from './Overlay.tsx';
import { siteFor } from '../sites.ts';

const mount = () => createRoot(document.getElementById('root')!).render(<StrictMode><Overlay /></StrictMode>);

// Clickjacking guard. Inside a frame, render only after our content script (the parent) sends {type:'rp-init', nonce} with the nonce from
// this page's own URL, and only if the parent's origin is one of the streaming sites; a stranger's page that frames overlay.html (the manifest
// also limits who may) renders nothing to click. Limit: a script running inside a listed site could still frame us and pick its own nonce.
// A top-level tab (the "Open in a new tab" fallback, the options flow) cannot be clickjacked and renders at once.
const siteOrigin = (o: string) => { try { const u = new URL(o); return (u.protocol === 'https:' && !!siteFor(u.hostname)) || (__RP_DEV__ && u.hostname === '127.0.0.1'); } catch { return false; } };
if (window.parent === window) mount();
else {
  const nonce = new URLSearchParams(location.search).get('n');
  const onInit = (e: MessageEvent) => {
    if (e.source !== window.parent || !nonce || e.data?.type !== 'rp-init' || e.data.nonce !== nonce || !siteOrigin(e.origin)) return;
    window.removeEventListener('message', onInit);
    mount();
  };
  window.addEventListener('message', onInit);
}
