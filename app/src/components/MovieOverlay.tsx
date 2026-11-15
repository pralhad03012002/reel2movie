import { useEffect, useId, useLayoutEffect, useRef, useState, type FC, type ReactNode } from 'react';
import {
  animate,
  motion,
  usePresence,
  useMotionValue,
  useReducedMotion,
  useTransform,
  type Variants,
} from 'framer-motion';
import { Check, ExternalLink, Play, Star, Volume2, VolumeX, X } from 'lucide-react';
import './tokens.css';
import { REF_DATE } from './catalog';
import type { Movie, Provider } from './types';

const EASE = [0.23, 1, 0.32, 1] as const;
const NOW = REF_DATE.getTime(); // demo data is pinned to a fixed date (same as Browse), so 'ago' is relative to it, not the wall clock

/* ---------- helpers ---------- */

// anchored so channel-style names ("Lionsgate Play Apple TV Channel") fall through to the generic search
const SEARCH: [RegExp, (q: string) => string][] = [
  [/^netflix/, (q) => `https://www.netflix.com/search?q=${q}`],
  [/^amazon (prime )?video/, (q) => `https://www.primevideo.com/search?phrase=${q}`],
  [/^(jio)?hotstar/, (q) => `https://www.hotstar.com/in/explore?search_query=${q}`],
  [/^zee5/, (q) => `https://www.zee5.com/search?q=${q}`],
  [/^sony ?liv$/, (q) => `https://www.sonyliv.com/search?searchTerm=${q}`],
  [/^apple tv( store| plus)?$/, (q) => `https://tv.apple.com/in/search?term=${q}`],
  [/^youtube/, (q) => `https://www.youtube.com/results?search_query=${q}`],
  [/^google play/, (q) => `https://play.google.com/store/search?q=${q}&c=movies`],
];
const hasSearch = (name: string) => SEARCH.some(([re]) => re.test(name.toLowerCase()));

const providerUrl = (title: string, provider?: string) => {
  const q = encodeURIComponent(title);
  const hit = provider ? SEARCH.find(([re]) => re.test(provider.toLowerCase())) : undefined;
  if (hit) return hit[1](q);
  return `https://www.google.com/search?q=${encodeURIComponent(`watch ${title}${provider ? ` on ${provider}` : ''}`).replace(/%20/g, '+')}`;
};

const initials = (name: string) =>
  name
    .replace(/^@/, '')
    .split(/[\s._-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]!.toUpperCase())
    .join('');

const hue = (s: string) => [...s].reduce((a, c) => (a * 31 + c.charCodeAt(0)) % 360, 7);

const ago = (iso: string) => {
  const d = Math.max(0, Math.round((NOW - new Date(iso).getTime()) / 864e5));
  if (d < 1) return 'today';
  if (d < 7) return `${d} day${d === 1 ? '' : 's'} ago`;
  if (d < 31) return `${Math.round(d / 7)} wk ago`;
  if (d < 365) return `${Math.round(d / 30)} mo ago`;
  const y = Math.round(d / 365);
  return `${y} yr${y === 1 ? '' : 's'} ago`;
};

const runtime = (m: number | null) => (m ? (m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m}m`) : null);

const Avatar: FC<{ name: string; size?: number; ring?: boolean }> = ({ name, size = 28, ring }) => (
  <span
    aria-hidden
    className="inline-flex shrink-0 items-center justify-center rounded-full font-semibold"
    style={{
      width: size,
      height: size,
      fontSize: size * 0.38,
      background: `hsl(${hue(name)} 22% 22%)`,
      color: `hsl(${hue(name)} 40% 82%)`,
      boxShadow: ring ? '0 0 0 2px var(--rp-surface)' : 'inset 0 0 0 1px var(--rp-line)',
    }}
  >
    {initials(name)}
  </span>
);

const item: Variants = {
  hidden: { opacity: 0, y: 10 },
  show: { opacity: 1, y: 0, transition: { duration: 0.32, ease: EASE } },
  exit: { opacity: 0, transition: { duration: 0.1 } },
};
const Item: FC<{ children: ReactNode; className?: string }> = ({ children, className }) => (
  <motion.div variants={item} className={className}>
    {children}
  </motion.div>
);

const Label: FC<{ children: ReactNode }> = ({ children }) => (
  <h3 className="mb-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--rp-faint)]">{children}</h3>
);

// last card the user pressed/keyed on (the shell/browse need not cooperate); validated at use
let trigger: HTMLElement | null = null;
if (typeof document !== 'undefined') {
  const t = (e: Event) => { trigger = (e.target as HTMLElement)?.closest?.('.bs-card') as HTMLElement | null; };
  document.addEventListener('pointerdown', t, true);
  document.addEventListener('keydown', t, true);
}
const cardRect = (el: HTMLElement | null) => {
  if (!el || !el.isConnected) return null;
  const r = (el.querySelector('img') ?? el).getBoundingClientRect();
  return r.width > 20 && r.height > 20 && r.bottom > 0 && r.top < innerHeight ? r : null;
};
const lerp = (a: number, b: number, v: number) => a + (b - a) * v;

const FOCUSABLE = 'a[href],button:not([disabled]),[tabindex]:not([tabindex="-1"])';

/* ---------- trailer as the hero background ---------- */

// Autoplays muted behind the title. The still backdrop stays underneath until YouTube reports "playing",
// so the player's red play button and spinner are never seen. Clicks pass through (no controls).
const HeroTrailer: FC<{ trailerKey: string; backdrop: string; title: string; live: boolean }> = ({ trailerKey, backdrop, title, live }) => {
  const frame = useRef<HTMLIFrameElement>(null);
  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(true);
  const send = (func: string) => frame.current?.contentWindow?.postMessage(JSON.stringify({ event: 'command', func, args: '' }), '*');
  useEffect(() => {
    const on = (e: MessageEvent) => {
      if (e.source !== frame.current?.contentWindow || typeof e.data !== 'string') return;
      try { if (JSON.parse(e.data).info?.playerState === 1) setPlaying(true); } catch { /* not a player message */ }
    };
    window.addEventListener('message', on);
    return () => window.removeEventListener('message', on);
  }, []);
  return (
    <>
      <img src={backdrop} alt="" className="absolute inset-0 h-full w-full object-cover" />
      {live && (
        <iframe
          ref={frame}
          title={`${title} trailer`}
          src={`https://www.youtube-nocookie.com/embed/${trailerKey}?autoplay=1&mute=1&controls=0&loop=1&playlist=${trailerKey}&playsinline=1&rel=0&modestbranding=1&iv_load_policy=3&disablekb=1&fs=0&enablejsapi=1`}
          allow="autoplay; encrypted-media"
          tabIndex={-1}
          onLoad={() => frame.current?.contentWindow?.postMessage(JSON.stringify({ event: 'listening', id: 1 }), '*')}
          className="pointer-events-none absolute left-1/2 top-1/2 max-w-none -translate-x-1/2 -translate-y-1/2 border-0 transition-opacity duration-300"
          style={{ width: 'max(100cqw, 177.78cqh)', height: 'max(56.25cqw, 100cqh)', opacity: playing ? 1 : 0 }}
        />
      )}
      {playing && (
        <button
          type="button"
          aria-label={muted ? 'Turn trailer sound on' : 'Turn trailer sound off'}
          onClick={() => { send(muted ? 'unMute' : 'mute'); setMuted(!muted); }}
          className="absolute bottom-3 right-3 z-10 inline-flex h-11 w-11 items-center justify-center rounded-full bg-black/55 text-white backdrop-blur-sm transition-[transform,background-color] duration-150 hover:bg-black/75 active:scale-[0.94]"
        >
          {muted ? <VolumeX size={18} aria-hidden /> : <Volume2 size={18} aria-hidden />}
        </button>
      )}
    </>
  );
};

/* ---------- overlay ---------- */

// Extension: the site we are on. Its provider links go to the site's own search, in the same tab.
export interface SiteHint { matches: (providerName: string) => boolean; searchUrl: (title: string) => string; target?: string }

export const MovieOverlay: FC<{ movie: Movie; myServices: string[]; onClose: () => void; onToggleWatched: (id: string) => void; onRemove?: (id: string) => void; siteHint?: SiteHint; compact?: boolean; trailer?: 'embed' | 'link' }> = ({
  movie,
  myServices,
  onClose,
  onToggleWatched,
  onRemove,
  siteHint,
  compact: c, // extension popup: smaller hero, poster and title
  trailer = 'embed', // 'link': no player (YouTube refuses embeds inside extension pages), just a Watch trailer link
}) => {
  const reduce = useReducedMotion();
  const [present, safeToRemove] = usePresence();
  const titleId = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState({ w: typeof window === 'undefined' ? 1280 : window.innerWidth, h: typeof window === 'undefined' ? 900 : window.innerHeight });
  const [trailerReady, setTrailerReady] = useState(false);
  const [allCreators, setAllCreators] = useState(false);
  const narrow = box.w < 640;
  const panelRef = useRef<HTMLDivElement>(null);
  const ghostRef = useRef<HTMLImageElement>(null);
  const down = useRef(false);
  const [opener] = useState(() => {
    const t = trigger?.isConnected ? trigger : (document.activeElement as HTMLElement | null);
    trigger = null;
    return t;
  });
  const [src] = useState(() => (reduce ? null : cardRect(opener)));
  const p = useMotionValue(src ? 0 : 1);
  // card rect as insets of the full-viewport root, plus the poster ghost placed exactly on it
  const fl = useRef({ t: 0, r: 0, b: 0, l: 0 });
  const measureFlip = (r: DOMRect) => {
    const root = rootRef.current!;
    fl.current = { t: r.top, l: r.left, r: root.clientWidth - r.right, b: root.clientHeight - r.bottom };
    Object.assign(ghostRef.current!.style, { left: `${r.left}px`, top: `${r.top}px`, width: `${r.width}px`, height: `${r.height}px` });
  };
  const clipPath = useTransform(p, (v) => {
    if (v >= 1) return 'none';
    const f = fl.current;
    return `inset(${lerp(f.t, 0, v)}px ${lerp(f.r, 0, v)}px ${lerp(f.b, 0, v)}px ${lerp(f.l, 0, v)}px round ${lerp(10, 0, v)}px)`;
  });
  const coverOpacity = useTransform(p, (v) => Math.max(0, 1 - v * 1.5));

  // focus in, scroll lock, measure, open (animation starts after the first painted frame of the mounted dialog)
  useLayoutEffect(() => {
    const root = rootRef.current!;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    root.querySelector<HTMLElement>('[data-close]')?.focus({ preventScroll: true });
    const measure = () => setBox({ w: root.clientWidth, h: root.clientHeight });
    measure();
    let open: ReturnType<typeof animate> | undefined;
    let raf = 0;
    if (src) {
      measureFlip(src);
      root.style.clipPath = clipPath.get();
      raf = requestAnimationFrame(() => {
        raf = requestAnimationFrame(() => { open = animate(p, 1, { duration: 0.44, ease: EASE }); });
      });
    }
    const ro = new ResizeObserver(measure);
    ro.observe(root);
    return () => {
      cancelAnimationFrame(raf);
      open?.stop();
      ro.disconnect();
      document.body.style.overflow = prev;
      if (opener && document.contains(opener)) opener.focus({ preventScroll: true });
    };
  }, []);

  // exit: shrink the dialog back into the card (content has faded first), then release
  useEffect(() => {
    if (present) return;
    const el = panelRef.current;
    const r = cardRect(opener);
    if (!el || !r || reduce) {
      const a = el && animate(el, { opacity: 0 }, { duration: 0.18, ease: EASE });
      a ? a.then(safeToRemove) : safeToRemove?.();
      return;
    }
    let a: ReturnType<typeof animate> | undefined;
    const t = setTimeout(() => {
      el.scrollTop = 0;
      measureFlip(cardRect(opener) ?? r);
      a = animate(p, 0, { duration: 0.34, ease: EASE });
      a.then(() => safeToRemove?.());
    }, 110);
    return () => { clearTimeout(t); a?.stop(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [present]);

  // iframe waits for the open animation to settle
  useEffect(() => {
    const t = setTimeout(() => setTrailerReady(true), reduce ? 0 : 200);
    return () => clearTimeout(t);
  }, [reduce]);

  // Esc and the Tab trap live on the document so they also hold when focus has fallen to <body> or leaked out
  useEffect(() => {
    if (!present) return;
    const root = rootRef.current!;
    const tabbables = () => [...root.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) => !el.closest('[inert]') && el.offsetParent !== null);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        onClose();
      } else if (e.key === 'Tab') {
        const els = tabbables();
        const i = els.indexOf(document.activeElement as HTMLElement);
        if (!els.length) return;
        if (e.shiftKey ? i <= 0 : i < 0 || i === els.length - 1) { e.preventDefault(); els[e.shiftKey ? els.length - 1 : 0]!.focus(); }
      }
    };
    const onFocusIn = (e: FocusEvent) => { if (!root.contains(e.target as Node)) tabbables()[0]?.focus(); };
    document.addEventListener('keydown', onKey, true);
    document.addEventListener('focusin', onFocusIn);
    return () => {
      document.removeEventListener('keydown', onKey, true);
      document.removeEventListener('focusin', onFocusIn);
    };
  }, [present, onClose]);

  const m = movie;
  const mine = (p: Provider) => myServices.includes(p.name);
  const mineFirst = (a: Provider, b: Provider) => +mine(b) - +mine(a);
  const streams = m.providers.filter((p) => p.kind === 'stream').sort(mineFirst);
  const rents = m.providers.filter((p) => p.kind === 'rent').sort(mineFirst);
  const primary: Provider | undefined = (siteHint ? m.providers.find((p) => siteHint.matches(p.name)) : undefined) ?? streams.find((p) => hasSearch(p.name)) ?? streams[0] ?? m.providers[0];
  const where = (name?: string) => (siteHint && name && siteHint.matches(name) ? { href: siteHint.searchUrl(m.title), target: siteHint.target ?? '_blank' } : { href: providerUrl(m.title, name), target: '_blank' });
  const meta = [m.year ? String(m.year) : null, m.mediaType === 'tv' ? (m.seasons ? `${m.seasons} season${m.seasons === 1 ? '' : 's'}` : null) : runtime(m.runtimeMin)].filter(Boolean);
  const n = m.recommendations.length;
  const recs = [...m.recommendations].sort((a, b) => +new Date(b.at) - +new Date(a.at));
  const shown = allCreators ? recs : recs.slice(0, 4);

  const radius = narrow ? '22px 22px 0 0' : c ? 0 : 20;

  const link =
    'inline-flex min-h-11 items-center justify-center gap-2 rounded-full px-5 text-[15px] font-semibold transition-[transform,background-color,border-color] duration-150 active:scale-[0.97]';

  return (
    <motion.div
      ref={rootRef}
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      // close on backdrop only when the press AND the release both landed on it (not after a drag ending on it)
      onPointerDown={(e) => { down.current = e.target === e.currentTarget; }}
      onClick={(e) => down.current && e.target === e.currentTarget && onClose()}
      style={{ clipPath }}
      className={`fixed inset-0 z-50 flex justify-center ${c ? 'items-stretch' : 'items-end sm:items-center sm:p-6'}`}
    >
      <motion.div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-[rgb(6_6_8/0.68)] backdrop-blur-[14px]"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.28, ease: EASE }}
      />

      <motion.div
        ref={panelRef}
        className="rp-hide-scroll relative w-full max-w-[1000px] overflow-y-auto overscroll-contain bg-[var(--rp-surface)] shadow-[0_40px_120px_-20px_rgb(0_0_0/0.9),0_0_0_1px_var(--rp-line)]"
        style={{
          borderRadius: radius,
          maxHeight: narrow ? 'calc(100dvh - 12px)' : c ? '100dvh' : '90vh',
          height: narrow ? 'calc(100dvh - 12px)' : c ? '100dvh' : undefined,
        }}
        initial={src ? false : { opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.16, ease: EASE }}
      >
        <motion.div
          className="relative"
          initial={{ scale: reduce || src ? 1 : 0.96 }}
          animate={{ scale: 1 }}
          transition={{ duration: 0.36, ease: EASE }}
        >
          <motion.div
            initial="hidden"
            animate="show"
            exit="exit"
            variants={{ hidden: {}, show: { transition: { delayChildren: reduce ? 0 : 0.16, staggerChildren: 0.04 } }, exit: {} }}
          >
            {/* sticky close */}
            <div className="sticky top-0 z-30 h-0">
              <button
                data-close
                type="button"
                aria-label="Close"
                onClick={onClose}
                className="absolute right-3 top-3 inline-flex h-11 w-11 items-center justify-center rounded-full bg-black/55 text-white backdrop-blur-sm transition-[transform,background-color] duration-150 hover:bg-black/75 active:scale-[0.94]"
              >
                <X size={20} />
              </button>
            </div>

            <Item>
              <div className={`relative overflow-hidden [container-type:size] ${c ? 'h-[150px]' : 'h-[220px] sm:h-[360px]'}`}>
                {m.trailerKey && trailer === 'embed' ? <HeroTrailer trailerKey={m.trailerKey} backdrop={m.backdrop} title={m.title} live={trailerReady && present} /> : <img src={m.backdrop} alt="" className="h-full w-full object-cover" />}
                <div className="rp-hero-fade pointer-events-none absolute inset-0" />
              </div>
            </Item>

            <div className={`relative px-5 pb-8 ${c ? '' : 'sm:px-9'}`}>
              <div className={`flex items-end ${c ? '-mt-14 gap-4' : '-mt-24 gap-5 sm:-mt-32 sm:gap-7'}`}>
                <Item className={c ? 'shrink-0' : 'hidden shrink-0 sm:block'}>
                  <img
                    src={m.poster}
                    alt={`${m.title} poster`}
                    className={`aspect-[2/3] ${c ? 'w-[92px]' : 'w-[190px]'} rounded-xl object-cover shadow-[0_18px_40px_-10px_rgb(0_0_0/0.8),0_0_0_1px_var(--rp-line)]`}
                  />
                </Item>
                <div className="min-w-0 flex-1 pb-1">
                  <Item>
                    <h2 id={titleId} className={`rp-display font-semibold leading-[1.02] [text-shadow:0_2px_24px_rgb(0_0_0/0.6)] ${c ? 'text-[26px]' : 'text-[34px] sm:text-[52px]'}`}>
                      {m.title}
                    </h2>
                  </Item>
                  <Item className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2 text-[14px] text-[var(--rp-muted)]">
                    {meta.map((t, i) => (
                      <span key={i}>{t}</span>
                    ))}
                    <span className="inline-flex items-center gap-1 font-semibold text-[var(--rp-accent)]">
                      <Star size={14} fill="currentColor" aria-hidden />
                      <span aria-label={`TMDB rating ${m.rating.toFixed(1)} out of 10`}>{m.rating.toFixed(1)}</span>
                    </span>
                    {m.mediaType === 'tv' && (
                      <span className="rounded-full border border-[var(--rp-line-strong)] px-2.5 py-0.5 text-[12px] font-medium text-[var(--rp-text)]">Series</span>
                    )}
                  </Item>
                  <Item className="mt-3 flex flex-wrap gap-2">
                    {m.genres.map((g) => (
                      <span key={g} className="rounded-full bg-[var(--rp-raised)] px-3 py-1 text-[12.5px] text-[var(--rp-muted)]">
                        {g}
                      </span>
                    ))}
                  </Item>
                </div>
              </div>

              <Item className="mt-6 flex flex-wrap gap-3">
                <a
                  {...where(primary?.name)}
                  rel="noopener noreferrer"
                  className={`${link} bg-[var(--rp-accent)] text-[var(--rp-accent-ink)] hover:brightness-110`}
                >
                  <Play size={17} fill="currentColor" aria-hidden />
                  {primary ? 'Watch now' : 'Find where to watch'}
                </a>
                <button
                  type="button"
                  aria-pressed={m.watched}
                  onClick={() => onToggleWatched(m.id)}
                  className={`${link} border ${m.watched ? 'border-[var(--rp-accent)] text-[var(--rp-accent)]' : 'border-[var(--rp-line-strong)] hover:border-[var(--rp-muted)]'}`}
                >
                  <span className="relative inline-flex h-[18px] w-[18px] items-center justify-center">
                    <motion.span
                      className="absolute inset-0 rounded-full"
                      animate={{ scale: m.watched ? 1 : 0.6, opacity: m.watched ? 1 : 0, backgroundColor: 'var(--rp-accent)' }}
                      transition={{ duration: 0.2, ease: EASE }}
                    />
                    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" strokeWidth={3} strokeLinecap="round" strokeLinejoin="round" className="relative" aria-hidden>
                      <motion.path
                        d="M6 12.5l4 4 8-9"
                        initial={false}
                        animate={{ pathLength: m.watched ? 1 : 0, opacity: m.watched ? 1 : 0 }}
                        transition={{ duration: 0.26, ease: EASE, delay: m.watched ? 0.06 : 0 }}
                        stroke="var(--rp-accent-ink)"
                      />
                    </svg>
                    {!m.watched && <Check size={18} className="absolute text-[var(--rp-muted)]" aria-hidden />}
                  </span>
                  Mark as watched
                </button>
                {m.trailerKey && trailer === 'link' && (
                  <a href={`https://www.youtube.com/watch?v=${encodeURIComponent(m.trailerKey)}`} target="_blank" rel="noopener noreferrer" className={`${link} border border-[var(--rp-line-strong)] hover:border-[var(--rp-muted)]`}>
                    <ExternalLink size={16} aria-hidden /> Watch trailer
                  </a>
                )}
              </Item>

              <div className="mt-9 grid gap-9 md:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)] md:gap-12">
                <div className="min-w-0 space-y-8">
                  <Item>
                    {m.tagline && <p className="rp-display mb-3 text-[19px] italic text-[var(--rp-accent)]/90">{m.tagline}</p>}
                    <p className="max-w-[62ch] text-[16px] leading-[1.65] text-[var(--rp-text)]/90">{m.overview}</p>
                  </Item>
                  {m.director && (
                    <Item>
                      <Label>{m.mediaType === 'tv' ? 'Created by' : 'Director'}</Label>
                      <p className="text-[16px]">{m.director}</p>
                    </Item>
                  )}
                  {m.cast.length > 0 && (
                    <Item>
                      <Label>Cast</Label>
                      <ul className="grid grid-cols-1 gap-x-6 gap-y-3.5 min-[480px]:grid-cols-2 lg:grid-cols-3">
                        {m.cast.slice(0, 6).map((c) => (
                          <li key={c.name} className="flex items-center gap-3">
                            <Avatar name={c.name} size={40} />
                            <div className="min-w-0 leading-tight">
                              <p className="truncate text-[14.5px] font-medium">{c.name}</p>
                              <p className="mt-0.5 truncate text-[12.5px] text-[var(--rp-muted)]">{c.character}</p>
                            </div>
                          </li>
                        ))}
                      </ul>
                    </Item>
                  )}
                </div>

                <div className="min-w-0 space-y-8">
                  <Item>
                    <Label>Where to watch</Label>
                    {m.providers.length ? (
                      <div className="flex flex-wrap items-center gap-2">
                        {streams.map((p) => (
                          <a key={p.name} {...where(p.name)} rel="noopener noreferrer"
                            className={`inline-flex min-h-11 items-center gap-1.5 rounded-full border ${mine(p) ? 'border-[var(--rp-text)] bg-white/[0.06]' : 'border-[var(--rp-line-strong)]'} px-4 text-[14px] font-medium transition-[transform,border-color] duration-150 hover:border-[var(--rp-muted)] active:scale-[0.97]`}>
                            {p.name}<ExternalLink size={12} className="text-[var(--rp-faint)]" aria-hidden />
                          </a>
                        ))}
                        {rents.map((p) => (
                          <a key={p.name} {...where(p.name)} rel="noopener noreferrer"
                            className="inline-flex min-h-11 items-center gap-1.5 rounded-full px-3 text-[13px] text-[var(--rp-muted)] transition-[transform,color] duration-150 hover:text-[var(--rp-text)] active:scale-[0.97]">
                            {p.name} <span className="text-[11px] text-[var(--rp-faint)]">rent</span>
                          </a>
                        ))}
                      </div>
                    ) : (
                      <p className="text-[14px] text-[var(--rp-muted)]">Not listed on a streaming service in your region yet.</p>
                    )}
                  </Item>

                  <Item>
                    <div className="mb-4 flex items-center gap-3">
                      <span className="flex -space-x-2">
                        {m.recommendations.slice(0, 4).map((r, i) => (
                          <Avatar key={r.handle + i} name={r.creator} size={30} ring />
                        ))}
                      </span>
                      <p className="text-[14.5px] font-semibold text-[var(--rp-accent)]">
                        Recommended by {n} creator{n === 1 ? '' : 's'}
                      </p>
                    </div>
                    <ul className="space-y-4">
                      {shown.map((r, i) => (
                        <li key={r.handle + i} className="flex gap-3">
                          <Avatar name={r.creator} size={34} />
                          <div className="min-w-0">
                            <p className="text-[14px] leading-tight">
                              {r.postUrl ? <a href={r.postUrl} target="_blank" rel="noopener noreferrer" className="font-medium underline-offset-4 hover:underline">{r.creator}</a> : <span className="font-medium">{r.creator}</span>}
                              {r.handle && <> <span className="text-[var(--rp-muted)]">{r.handle}</span></>}
                            </p>
                            <p className="mt-0.5 text-[12px] text-[var(--rp-faint)]">{ago(r.at)}</p>
                            {r.quote && <p className="rp-display mt-1.5 text-[14.5px] italic leading-snug text-[var(--rp-text)]/80">&ldquo;{r.quote}&rdquo;</p>}
                          </div>
                        </li>
                      ))}
                    </ul>
                    {recs.length > 4 && (
                      <button type="button" onClick={() => setAllCreators((v) => !v)}
                        className="mt-3 inline-flex min-h-11 items-center text-[13.5px] font-medium text-[var(--rp-muted)] underline-offset-4 hover:text-[var(--rp-text)] hover:underline">
                        {allCreators ? 'Show fewer' : `Show all ${recs.length}`}
                      </button>
                    )}
                  </Item>

                  {onRemove && <Item>
                    <button type="button" onClick={() => { if (confirm(`Remove "${m.title}" from your list?`)) { onRemove(m.id); onClose(); } }}
                      className="inline-flex min-h-11 items-center text-[13px] text-[var(--rp-faint)] underline-offset-4 transition-colors hover:text-[var(--rp-danger)] hover:underline">
                      Remove from my list
                    </button>
                  </Item>}
                </div>
              </div>
            </div>
          </motion.div>
        </motion.div>
      </motion.div>

      {!reduce && (
        <motion.img
          ref={ghostRef}
          aria-hidden
          alt=""
          src={m.poster}
          className="pointer-events-none absolute z-20 object-cover"
          style={{ opacity: coverOpacity, borderRadius: 10 }}
        />
      )}
    </motion.div>
  );
};
