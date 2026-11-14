import { FC, FormEvent, useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { Plus, X } from 'lucide-react';
import './tokens.css';
import type { Post, Settings } from '../useReelPicks';

const REGIONS: [string, string][] = [
  ['IN', 'India'], ['US', 'United States'], ['GB', 'United Kingdom'], ['CA', 'Canada'], ['AU', 'Australia'],
  ['AE', 'United Arab Emirates'], ['SG', 'Singapore'], ['DE', 'Germany'], ['FR', 'France'],
];
const STAGES: Record<string, string> = {
  downloading: 'Downloading…',
  transcribing: 'Transcribing with ElevenLabs…',
  'transcribing-local': 'Transcribing on your computer…',
  extracting: 'Finding movies…',
  matching: 'Matching titles…',
};
const status = (p: Post) => (p.status === 'failed' ? `Failed: ${p.error || 'unknown error'}` : p.status === 'processing' ? STAGES[p.stage ?? ''] ?? 'Processing…' : 'Queued');

const field = 'h-11 w-full rounded-xl border border-[var(--rp-line-strong)] bg-[var(--rp-bg)] px-3.5 text-[14px] text-[var(--rp-text)] placeholder:text-[var(--rp-faint)] focus:border-[var(--rp-muted)] focus:outline-none';
const primary = 'inline-flex h-11 shrink-0 items-center justify-center gap-1.5 rounded-xl bg-[#f5f2ea] px-4 text-[14px] font-semibold text-[#0a0a0c] transition-[transform,filter] duration-150 hover:brightness-95 active:scale-[0.97]';

/** Paste a reel link to queue it. Used in the account menu and on the empty home screen. */
export const PasteForm: FC<{ onAdd: (text: string) => boolean }> = ({ onAdd }) => {
  const [text, setText] = useState('');
  const submit = (e: FormEvent) => { e.preventDefault(); if (onAdd(text)) setText(''); };
  return (
    <form onSubmit={submit} className="flex gap-2">
      <input type="url" inputMode="url" required maxLength={500} pattern="https://.*" value={text} onChange={(e) => setText(e.target.value)}
        placeholder="https://www.instagram.com/reel/…" aria-label="Reel link" className={field} />
      <button type="submit" className={primary}><Plus size={16} aria-hidden /> Add</button>
    </form>
  );
};

interface Props {
  name: string;
  email: string;
  settings: Settings;
  services: string[];
  posts: Post[];
  onAdd: (text: string) => boolean;
  onDismiss: (id: string) => void;
  onRegion: (r: string) => void;
  onService: (name: string, on: boolean) => void;
  onLocalStt: (on: boolean) => void;
  onSignOut: () => void;
}

export const AccountMenu: FC<Props> = ({ name, email, settings, services, posts, onAdd, onDismiss, onRegion, onService, onLocalStt, onSignOut }) => {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const reduce = useReducedMotion();
  const working = posts.some((p) => p.status !== 'failed');

  useEffect(() => {
    if (!open) return;
    const down = (e: PointerEvent) => { if (!wrap.current?.contains(e.target as Node)) setOpen(false); };
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') { setOpen(false); trigger.current?.focus(); } };
    document.addEventListener('pointerdown', down);
    document.addEventListener('keydown', key);
    return () => { document.removeEventListener('pointerdown', down); document.removeEventListener('keydown', key); };
  }, [open]);

  const initial = (name || email || '?').trim()[0]!.toUpperCase();
  const mine = new Set(settings.services);
  const label = 'mb-2 block text-[11px] font-medium uppercase tracking-[0.08em] text-[var(--rp-muted)]';

  return (
    <div ref={wrap} className="relative shrink-0">
      <button ref={trigger} type="button" onClick={() => setOpen((o) => !o)} aria-haspopup="dialog" aria-expanded={open}
        aria-label={`Account and reels${working ? ' (processing)' : ''}`}
        className="relative inline-flex h-10 w-10 items-center justify-center rounded-full border border-[var(--rp-line-strong)] bg-[var(--rp-surface)] text-[15px] font-semibold transition-[transform,background-color] duration-150 hover:bg-[var(--rp-raised)] active:scale-[0.95]">
        {initial}
        {working && <span aria-hidden className="absolute -right-0.5 -top-0.5 h-3 w-3 animate-pulse rounded-full border-2 border-[var(--rp-bg)] bg-[var(--rp-accent)]" />}
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            role="dialog" aria-label="Account and reels"
            className="absolute right-0 top-[calc(100%+8px)] z-50 max-h-[min(80vh,640px)] w-[min(360px,calc(100vw-32px))] overflow-y-auto rounded-2xl border border-[rgb(255_255_255/0.08)] bg-[#1c1c1f] p-4 shadow-[0_24px_60px_-12px_rgb(0_0_0/0.7)]"
            style={{ transformOrigin: 'top right' }}
            initial={reduce ? { opacity: 0 } : { opacity: 0, scale: 0.96, y: -4 }}
            animate={{ opacity: 1, scale: 1, y: 0, transition: { duration: 0.17, ease: [0.23, 1, 0.32, 1] } }}
            exit={{ opacity: 0, scale: 0.97, transition: { duration: 0.12 } }}
          >
            <p className="truncate text-[13px] text-[var(--rp-muted)]">{email}</p>

            <section className="mt-4">
              <label className={label}>Add a reel</label>
              <PasteForm onAdd={onAdd} />
              <p className="mt-2 text-[12px] leading-snug text-[var(--rp-faint)]">Or share a reel to ReelPicks from Instagram on your phone. Reels are processed while the owner’s computer is on.</p>
            </section>

            {posts.length > 0 && (
              <section className="mt-5">
                <span className={label}>Processing</span>
                <ul className="space-y-2">
                  {posts.map((p) => (
                    <li key={p.id} className="flex items-center gap-3 rounded-xl bg-white/[0.04] px-3 py-2.5">
                      <div className="min-w-0 flex-1">
                        <p className={`text-[13px] font-medium ${p.status === 'failed' ? 'text-[var(--rp-danger)]' : ''}`}>{status(p)}</p>
                        <p className="truncate text-[11.5px] text-[var(--rp-faint)]">{p.url}</p>
                      </div>
                      <button type="button" onClick={() => onDismiss(p.id)} aria-label="Dismiss" className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-[var(--rp-muted)] transition-colors hover:bg-white/[0.08] hover:text-[var(--rp-text)]"><X size={16} aria-hidden /></button>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            <section className="mt-5">
              <label htmlFor="rp-region" className={label}>Region</label>
              <select id="rp-region" value={settings.region} onChange={(e) => onRegion(e.target.value)} className={field}>
                {REGIONS.map(([code, n]) => <option key={code} value={code}>{n}</option>)}
              </select>
            </section>

            <fieldset className="mt-5 min-w-0 border-0 p-0">
              <legend className={label}>My services</legend>
              {services.length ? (
                <div className="flex flex-wrap gap-2">
                  {services.map((s) => (
                    <label key={s} className="relative cursor-pointer">
                      <input type="checkbox" checked={mine.has(s)} onChange={(e) => onService(s, e.target.checked)} className="peer absolute inset-0 m-0 cursor-pointer opacity-0" />
                      <span className="block rounded-full border border-[var(--rp-line-strong)] px-3.5 py-2 text-[13px] text-[var(--rp-muted)] transition-colors peer-checked:border-transparent peer-checked:bg-white/[0.12] peer-checked:text-white peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-white/40">{s}</span>
                    </label>
                  ))}
                </div>
              ) : (
                <p className="text-[12.5px] text-[var(--rp-faint)]">Services appear here once your movies have streaming info for this region.</p>
              )}
            </fieldset>

            <label className="mt-5 flex cursor-pointer items-start gap-3 text-[13px] leading-snug text-[var(--rp-muted)]">
              <input type="checkbox" checked={settings.localStt} onChange={(e) => onLocalStt(e.target.checked)} className="mt-0.5 h-4 w-4 shrink-0 accent-[#f5f2ea]" />
              Transcribe reels on my computer (local Whisper) instead of ElevenLabs
            </label>

            <div className="mt-5 flex items-center justify-between gap-3 border-t border-[var(--rp-line)] pt-4">
              <button type="button" onClick={onSignOut} className="inline-flex h-10 items-center rounded-full border border-[var(--rp-line-strong)] px-4 text-[13.5px] font-medium transition-[transform,background-color] duration-150 hover:bg-white/[0.06] active:scale-[0.97]">Sign out</button>
            </div>
            <p className="mt-4 text-[11px] leading-snug text-[var(--rp-faint)]">Movie data from TMDB. Streaming availability from JustWatch. This app uses the TMDB API but is not endorsed or certified by TMDB.</p>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};
