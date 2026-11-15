import { useEffect, useRef, useState } from 'react';
import { motion, useReducedMotion } from 'framer-motion';
import { parseConnectParam } from '../lib.js';

declare const chrome: undefined | {
  runtime?: {
    lastError?: { message?: string };
    sendMessage?: (id: string, msg: unknown, cb: (reply?: { ok: boolean; error?: string }) => void) => void;
  };
};

// Read once at load, then drop only the `connect` param from the address bar.
const extensionId = parseConnectParam(location.search);
{
  const url = new URL(location.href);
  if (url.searchParams.has('connect')) {
    url.searchParams.delete('connect');
    history.replaceState(null, '', url.pathname + url.search + url.hash);
  }
}

export const connectPending = !!extensionId;

const primary = 'inline-flex min-h-11 items-center justify-center rounded-xl bg-[#f5f2ea] px-4 text-[14px] font-semibold text-[#0a0a0c] transition-[transform,filter] duration-150 hover:brightness-95 active:scale-[0.97] focus-visible:outline-white aria-disabled:opacity-60';
const quiet = 'inline-flex min-h-11 items-center justify-center rounded-xl border border-[var(--rp-line)] px-4 text-[14px] font-medium text-white transition-colors focus-visible:outline-white hover:bg-white/[0.06]';

export const ConnectExtension = ({ user, onClose }: { user: { uid: string; email: string | null; refreshToken: string }; onClose: () => void }) => {
  const reduce = useReducedMotion();
  const btn = useRef<HTMLButtonElement>(null);
  const [status, setStatus] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const done = status?.ok;

  const panel = useRef<HTMLDivElement>(null);
  const closeBtn = useRef<HTMLButtonElement>(null);
  const latest = useRef({ onClose, busy });
  latest.current = { onClose, busy };

  // Once on mount: focus Connect, restore focus on unmount.
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    btn.current?.focus();
    return () => prev?.focus?.();
  }, []);

  // Stable listener (reads the latest props via the ref). Capture phase: Esc closes only this panel.
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation(); e.preventDefault();
        if (!latest.current.busy) latest.current.onClose();
      } else if (e.key === 'Tab' && panel.current) {
        const f = [...panel.current.querySelectorAll<HTMLElement>('button')];
        const first = f[0], last = f[f.length - 1], cur = document.activeElement;
        if (!panel.current.contains(cur)) { e.preventDefault(); first?.focus(); }
        else if (e.shiftKey && cur === first) { e.preventDefault(); last?.focus(); }
        else if (!e.shiftKey && cur === last) { e.preventDefault(); first?.focus(); }
      }
    };
    addEventListener('keydown', key, true);
    return () => removeEventListener('keydown', key, true);
  }, []);

  useEffect(() => { if (done) closeBtn.current?.focus(); }, [done]);

  const connect = () => {
    if (typeof chrome === 'undefined' || !chrome.runtime?.sendMessage) {
      setStatus({ ok: false, text: 'Open this page in Chrome with the extension installed.' });
      return;
    }
    if (busy) return;
    setBusy(true);
    try {
      chrome.runtime.sendMessage(extensionId, { type: 'connect', uid: user.uid, email: user.email ?? '', refreshToken: user.refreshToken }, (reply) => {
        setBusy(false);
        const err = chrome?.runtime?.lastError;
        if (err) setStatus({ ok: false, text: err.message || 'Could not reach the extension.' });
        else if (reply?.ok) setStatus({ ok: true, text: 'Connected. You can close this tab and open ReelPicks on any streaming site.' });
        else setStatus({ ok: false, text: reply?.error || 'The extension did not accept the connection.' });
      });
    } catch (e) {
      setBusy(false);
      setStatus({ ok: false, text: e instanceof Error ? e.message : 'Could not reach the extension.' });
    }
  };

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/60 p-4">
      <motion.div
        role="dialog" aria-modal="true" aria-labelledby="connect-title" aria-describedby="connect-body"
        ref={panel}
        initial={{ opacity: 0, y: reduce ? 0 : 12, scale: reduce ? 1 : 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.2, ease: [0.23, 1, 0.32, 1] }}
        className="w-full max-w-[26rem] rounded-2xl border border-[var(--rp-line)] bg-[#1c1c1f] p-6 shadow-[0_24px_60px_-12px_rgb(0_0_0/0.8)]"
      >
        <h2 id="connect-title" className="rp-display text-[20px] font-medium">Connect the ReelPicks browser extension</h2>
        <p id="connect-body" className="mt-2 text-[14.5px] leading-relaxed text-[var(--rp-muted)]">
          This connects the extension to <strong className="font-semibold text-white">{user.email || 'your account'}</strong>. It can read your list and mark movies watched, and keeps access to this ReelPicks account until you disconnect it in the extension.
        </p>
        <p role="status" className={`${status ? 'mt-4' : ''} text-[14px] leading-snug ${done ? 'text-white' : 'text-[#ff9b9b]'}`}>{status?.text}</p>
        <div className="mt-5 flex flex-wrap justify-end gap-2">
          <button ref={closeBtn} type="button" className={quiet} aria-disabled={busy} onClick={() => !busy && onClose()}>{done ? 'Close' : 'Not now'}</button>
          {!done && <button ref={btn} type="button" className={primary} aria-disabled={busy} onClick={connect}>Connect</button>}
        </div>
      </motion.div>
    </div>
  );
};
