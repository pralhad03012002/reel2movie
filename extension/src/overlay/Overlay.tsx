import { useCallback, useEffect, useMemo, useRef, useState, type FC, type ReactNode } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { RefreshCw, WifiOff, X } from 'lucide-react';
import { BrowseScreen } from '@app/components/BrowseScreen';
import { MovieOverlay, type SiteHint } from '@app/components/MovieOverlay';
import { buildGenres } from '@app/components/catalog';
import { ALL_GENRES, type Movie } from '@app/components/types';
import { providerOnSite, SITES } from '../sites.ts';
import { send, WEB_APP } from '../shared/bg.ts';

interface Settings { region: string; services: string[]; localStt: boolean }
type State =
  | { s: 'loading' }
  | { s: 'ok'; movies: Movie[]; settings: Settings; at: number }
  | { s: 'err'; msg: string; notConnected?: boolean };

const inFrame = window.parent !== window;
const close = () => (inFrame ? window.parent.postMessage({ type: 'rp-close' }, '*') : window.close());
const site = SITES.find((s) => s.id === new URLSearchParams(location.search).get('site')) ?? null;
const hint: SiteHint | undefined = site ? { matches: (n) => providerOnSite(site, n), searchUrl: site.searchUrl, target: '_top' } : undefined;
const onSiteMovie = (m: Movie) => !!site && m.providers.some((p) => providerOnSite(site, p.name));

const Msg: FC<{ title: string; children?: ReactNode; icon?: ReactNode }> = ({ title, children, icon }) => (
  <div className="ext-msg">
    <button type="button" className="bs-back bs-close ext-close" onClick={close} aria-label="Close"><X size={20} aria-hidden /></button>
    <div>
      {icon}
      <h2 className="rp-display text-[24px] font-medium">{title}</h2>
      <div className="mt-2 space-y-4 text-[14.5px] leading-relaxed text-[var(--rp-muted)]">{children}</div>
    </div>
  </div>
);

const Skeleton = () => (
  <div className="p-5" aria-busy="true" aria-label="Loading your picks">
    <div className="ext-skel h-9 w-48" />
    {[0, 1].map((r) => (
      <div key={r} className="mt-7">
        <div className="ext-skel mb-3 h-5 w-32" />
        <div className="flex gap-3.5 overflow-hidden">
          {Array.from({ length: 8 }, (_, i) => <div key={i} className="ext-skel aspect-[2/3] w-32 flex-none" style={{ animationDelay: `${i * 60}ms` }} />)}
        </div>
      </div>
    ))}
  </div>
);

const Account: FC<{ email: string; at?: number; refreshing: boolean; onRefresh: () => void; onDisconnect: () => void }> = ({ email, at, refreshing, onRefresh, onDisconnect }) => {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const reduce = useReducedMotion();
  useEffect(() => {
    if (!open) return;
    const down = (e: PointerEvent) => { if (!wrap.current?.contains(e.target as Node)) setOpen(false); };
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('pointerdown', down);
    document.addEventListener('keydown', key);
    return () => { document.removeEventListener('pointerdown', down); document.removeEventListener('keydown', key); };
  }, [open]);
  const item = 'flex h-10 w-full items-center rounded-lg px-3 text-left text-[14px] text-white/80 transition-[background-color,transform] duration-150 hover:bg-white/[0.07] hover:text-white active:scale-[0.98]';
  return (
    <div ref={wrap} className="relative shrink-0">
      <button type="button" aria-haspopup="dialog" aria-expanded={open} aria-label="ReelPicks account" onClick={() => setOpen((o) => !o)}
        className="ext-acct inline-flex h-9 w-9 items-center justify-center rounded-full border border-[var(--rp-line-strong)] bg-[var(--rp-surface)] text-[14px] font-semibold transition-[transform,background-color] duration-150 hover:bg-[var(--rp-raised)] active:scale-[0.95]">
        {(email || '?')[0].toUpperCase()}
      </button>
      <AnimatePresence>
        {open && (
          <motion.div role="dialog" aria-label="Account" style={{ transformOrigin: 'top right' }}
            className="absolute right-0 top-[calc(100%+8px)] z-50 w-[260px] rounded-2xl border border-white/10 bg-[#1c1c1f] p-2 shadow-[0_24px_60px_-12px_rgb(0_0_0/0.7)]"
            initial={reduce ? { opacity: 0 } : { opacity: 0, scale: 0.96, y: -4 }}
            animate={{ opacity: 1, scale: 1, y: 0, transition: { duration: 0.17, ease: [0.23, 1, 0.32, 1] } }}
            exit={{ opacity: 0, scale: 0.97, transition: { duration: 0.12 } }}>
            <p className="truncate px-3 pb-1 pt-2 text-[13px] text-[var(--rp-muted)]">{email || 'Connected'}</p>
            {at && <p className="px-3 pb-2 text-[12px] text-[var(--rp-faint)]">Updated {new Date(at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</p>}
            <button type="button" className={item} disabled={refreshing} onClick={() => { onRefresh(); setOpen(false); }}>Refresh</button>
            <a className={item} href={WEB_APP} target="_blank" rel="noopener noreferrer">Open ReelPicks web app</a>
            <button type="button" className={item} onClick={onDisconnect}>Disconnect</button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export const Overlay: FC = () => {
  const [st, setSt] = useState<State>({ s: 'loading' });
  const [refreshing, setRefreshing] = useState(false);
  const [onSite, setOnSite] = useState(!!site);
  const [openId, setOpenId] = useState<string | null>(null);
  const [toast, setToast] = useState('');
  const [notice, setNotice] = useState('');
  const [email, setEmail] = useState('');
  const root = useRef<HTMLDivElement>(null);

  const stRef = useRef(st);
  stRef.current = st;
  const revalidated = useRef(false); // a stale reply triggers exactly one quiet refresh
  const notConnected = () => setSt({ s: 'err', msg: 'Not connected', notConnected: true });

  // quiet: background refresh after a stale reply; no spinner, no toast, and the list the user is browsing is swapped in place.
  const load = useCallback(async (force = false, quiet = false) => {
    if (!quiet) setRefreshing(true);
    let r = await send({ type: force ? 'refresh' : 'getData' });
    if (r.retry) r = await send({ type: force ? 'refresh' : 'getData' }); // a connect/disconnect voided the fetch: once more
    if (!quiet) setRefreshing(false);
    if (r.notConnected) return notConnected();
    if (r.ok) {
      setSt({ s: 'ok', movies: r.movies, settings: r.settings, at: r.cachedAt });
      setNotice(r.stale && force ? 'Offline: showing your saved list' : '');
      if (r.stale && !force && !revalidated.current) { revalidated.current = true; void load(true, true); }
    } else if (stRef.current.s === 'ok') { if (force) setNotice(navigator.onLine ? "Couldn't refresh" : 'Offline: showing your saved list'); } // keep the list we have
    else setSt({ s: 'err', msg: r.error ?? 'Something went wrong' });
  }, []);

  useEffect(() => { if (inFrame) window.parent.postMessage({ type: 'rp-ready' }, '*'); void load(); send({ type: 'status' }).then((r) => setEmail(r.email ?? '')); root.current?.focus(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { // coming back to the tab: notice a disconnect made elsewhere, or a connect after the not-connected screen
    const check = async () => {
      if (document.visibilityState === 'hidden') return;
      const r = await send({ type: 'status' });
      if (!r.ok) return;
      setEmail(r.email ?? '');
      if (!r.connected) notConnected();
      else if (stRef.current.s === 'err') { setSt({ s: 'loading' }); void load(); }
    };
    window.addEventListener('focus', check);
    document.addEventListener('visibilitychange', check);
    return () => { window.removeEventListener('focus', check); document.removeEventListener('visibilitychange', check); };
  }, [load]);
  useEffect(() => { if (!toast) return; const t = setTimeout(() => setToast(''), 3500); return () => clearTimeout(t); }, [toast]);

  // Esc closes unless something inside (menu, popover, search text) wants it first; the movie dialog handles its own.
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if (e.altKey && e.shiftKey && e.code === 'KeyR') { e.preventDefault(); close(); return; }
      if (e.key !== 'Escape' || e.defaultPrevented) return;
      const t = e.target as HTMLInputElement;
      if (document.querySelector('[aria-expanded="true"]') || (t.tagName === 'INPUT' && t.value)) return;
      close();
    };
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, []);

  const movies = st.s === 'ok' ? st.movies : [];
  const settings = st.s === 'ok' ? st.settings : undefined;
  const shown = useMemo(() => (onSite && site ? movies.filter(onSiteMovie) : movies), [movies, onSite]);
  const genres = useMemo(() => buildGenres(shown), [shown]);
  const open = movies.find((m) => m.id === openId) ?? null;

  const setWatched = (id: string, watched: boolean) =>
    setSt((s) => (s.s === 'ok' ? { ...s, movies: s.movies.map((m) => (m.id === id ? { ...m, watched } : m)) } : s));
  const toggle = (id: string) => {
    const m = movies.find((x) => x.id === id);
    if (!m) return;
    setWatched(id, !m.watched);
    send({ type: 'setWatched', id, watched: !m.watched }).then((r) => { if (r.notConnected) notConnected(); else if (!r.ok) { setWatched(id, m.watched); setToast(r.error ?? 'Could not save'); } });
  };
  const disconnect = async () => { await send({ type: 'disconnect' }); notConnected(); };

  if (st.s === 'loading') return <div ref={root} tabIndex={-1} className="rp ext min-h-dvh outline-none"><Skeleton /></div>;
  const frame = (c: ReactNode) => <div ref={root} tabIndex={-1} className="rp ext min-h-dvh outline-none">{c}</div>;

  if (st.s === 'err') {
    const offline = !navigator.onLine;
    return frame(st.notConnected ? (
      <Msg title="Connect your ReelPicks account">
        <p>Sign in once on the ReelPicks web app and your picks show up here, on top of the site you are watching.</p>
        <a className="ext-btn" href={chrome.runtime.getURL('connect.html')} target="_blank" rel="noopener noreferrer">Connect account</a>
      </Msg>
    ) : (
      <Msg title={offline ? 'You are offline' : 'Could not load your picks'} icon={offline ? <WifiOff className="mx-auto mb-3 text-white/60" aria-hidden /> : undefined}>
        <p>{offline ? 'Check your connection and try again.' : st.msg}</p>
        <button type="button" className="ext-btn" onClick={() => { setSt({ s: 'loading' }); void load(); }}>Retry</button>
      </Msg>
    ));
  }

  if (!movies.length) {
    return frame(<Msg title="No picks yet">
      <p>Add a reel in the ReelPicks web app and its movie will appear here.</p>
      <a className="ext-btn" href={WEB_APP} target="_blank" rel="noopener noreferrer">Open ReelPicks</a>
    </Msg>);
  }

  const nOn = movies.filter(onSiteMovie).length;
  const strip = site && (
    <div className="ext-strip">
      <span className="ext-div" aria-hidden />
      <button type="button" className="ext-chip" aria-pressed={onSite} onClick={() => setOnSite(true)}>On {site.label}<small>{nOn}</small></button>
      <button type="button" className="ext-chip" aria-pressed={!onSite} onClick={() => setOnSite(false)}>All my picks<small>{movies.length}</small></button>
      <button type="button" className={`ext-icon${refreshing ? ' ext-spin' : ''}`} aria-label="Refresh" title="Refresh" disabled={refreshing} onClick={() => load(true)}><RefreshCw size={16} aria-hidden /></button>
    </div>
  );

  return frame(
    <>
      {onSite && site && !shown.length ? (
        <>
          <div className="ext-solo">{strip}</div>
          <Msg title={`Nothing on ${site.label} yet`}>
            <p>None of your picks are streaming here right now.</p>
            <button type="button" className="ext-btn" onClick={() => setOnSite(false)}>Show all my picks</button>
          </Msg>
        </>
      ) : (
        <BrowseScreen
          key={onSite ? 'site' : 'all'}
          movies={shown} genres={genres} initialGenre={ALL_GENRES} myServices={settings?.services ?? []}
          backIcon="close" onBack={close} strip={strip}
          account={<Account email={email} at={st.at} refreshing={refreshing} onRefresh={() => load(true)} onDisconnect={disconnect} />}
          onOpen={(m) => setOpenId(m.id)} onToggleWatched={toggle}
        />
      )}
      <AnimatePresence>
        {open && <MovieOverlay key={open.id} compact trailer="link" movie={open} myServices={settings?.services ?? []} siteHint={hint} onClose={() => setOpenId(null)} onToggleWatched={toggle} />}
      </AnimatePresence>
      {notice && (
        <div role="status" className="fixed bottom-16 left-1/2 z-[60] flex -translate-x-1/2 items-center gap-3 rounded-xl border border-white/10 bg-[#1c1c1f] py-2 pl-4 pr-2 text-[13.5px] shadow-[0_16px_40px_-8px_rgb(0_0_0/0.7)]">
          <span>{notice}</span>
          <button type="button" className="rounded-lg px-2.5 py-1.5 font-semibold hover:bg-white/[0.07]" onClick={() => { setNotice(''); void load(true); }}>Retry</button>
          <button type="button" aria-label="Dismiss" className="rounded-lg p-1.5 hover:bg-white/[0.07]" onClick={() => setNotice('')}><X size={14} aria-hidden /></button>
        </div>
      )}
      {toast && <div role="status" className="fixed bottom-4 left-1/2 z-[60] -translate-x-1/2 rounded-xl border border-white/10 bg-[#1c1c1f] px-4 py-2.5 text-[13.5px] shadow-[0_16px_40px_-8px_rgb(0_0_0/0.7)]">{toast}</div>}
    </>,
  );
};
