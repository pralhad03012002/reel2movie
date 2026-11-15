import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type FC, type ReactNode } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { Check, ChevronDown, ChevronLeft, ChevronRight, Search, SlidersHorizontal, Star, Undo2, X } from 'lucide-react';
import { ALL_GENRES, SORT_LABELS, type GenreSummary, type Movie, type SortKey } from './types';
import {
  NO_FILTERS, activeFilterCount, filterMovies, highlightRanges, queryTokens, searchMovies, sortMovies,
  type Filters, type Match,
} from './catalog';
import './Browse.css';

const EASE = [0.23, 1, 0.32, 1] as const;
type Status = 'unwatched' | 'watched';
const TOP_PICKS = 20;

/* ---------- small helpers ---------- */
const Hl: FC<{ text: string; tokens: string[] }> = ({ text, tokens }) => {
  const ranges = tokens.length ? highlightRanges(text, tokens) : [];
  if (!ranges.length) return <>{text}</>;
  const out: ReactNode[] = [];
  let at = 0;
  ranges.forEach(([s, e], i) => {
    if (s > at) out.push(text.slice(at, s));
    out.push(<mark key={i} className="bs-mark">{text.slice(s, e)}</mark>);
    at = e;
  });
  if (at < text.length) out.push(text.slice(at));
  return <>{out}</>;
};

const initials = (name: string) => name.replace(/[^\p{L}\s]/gu, '').split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join('').toUpperCase() || '?';
const hue = (s: string) => [...s].reduce((a, c) => (a * 31 + c.charCodeAt(0)) % 360, 7);

const Creators: FC<{ movie: Movie }> = ({ movie }) => {
  const n = movie.recommendations.length;
  return (
    <span className="bs-creators">
      <span className="bs-stack" aria-hidden>
        {movie.recommendations.slice(0, 3).map((r) => (
          <span key={r.handle} style={{ background: `hsl(${hue(r.handle)} 28% 30%)` }}>{initials(r.creator)}</span>
        ))}
      </span>
      <span>{n} {n === 1 ? 'creator' : 'creators'}</span>
    </span>
  );
};

/* ---------- tabs with sliding indicator ---------- */
interface TabItem { id: string; label: string; count: number }
const Tabs: FC<{ items: TabItem[]; value: string; onChange: (id: string) => void; label: string; variant: 'line' | 'pill'; muted?: boolean }> = ({
  items, value, onChange, label, variant, muted,
}) => {
  const list = useRef<HTMLDivElement>(null);
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});
  const [ind, setInd] = useState<{ x: number; w: number } | null>(null);
  const reduce = useReducedMotion();
  const sig = items.map((i) => `${i.label}${i.count}`).join('|');

  const measure = useCallback(() => {
    const el = refs.current[value];
    if (el) setInd((p) => (p && p.x === el.offsetLeft && p.w === el.offsetWidth ? p : { x: el.offsetLeft, w: el.offsetWidth }));
  }, [value]);
  useLayoutEffect(measure, [measure, sig]);
  useEffect(() => {
    const l = list.current;
    if (!l) return;
    const ro = new ResizeObserver(measure);
    ro.observe(l);
    document.fonts?.ready.then(measure);
    return () => ro.disconnect();
  }, [measure]);
  const first = useRef(true);
  useEffect(() => {
    const l = list.current, el = refs.current[value];
    if (!l || !el) return;
    l.scrollTo({ left: el.offsetLeft - (l.clientWidth - el.offsetWidth) / 2, behavior: first.current || reduce ? 'auto' : 'smooth' });
    first.current = false;
  }, [value, reduce]);

  const hasValue = items.some((t) => t.id === value);
  const onKey = (e: React.KeyboardEvent) => {
    const i = Math.max(0, items.findIndex((t) => t.id === value));
    const j = e.key === 'ArrowRight' ? (i + 1) % items.length : e.key === 'ArrowLeft' ? (i - 1 + items.length) % items.length : e.key === 'Home' ? 0 : e.key === 'End' ? items.length - 1 : -1;
    if (j < 0) return;
    e.preventDefault();
    onChange(items[j].id);
    requestAnimationFrame(() => refs.current[items[j].id]?.focus());
  };

  return (
    <div ref={list} role="tablist" aria-label={label} onKeyDown={onKey} className={`bs-tabs bs-tabs-${variant} rp-hide-scroll`} data-muted={muted || undefined}>
      {ind && (
        <motion.span
          aria-hidden
          className="bs-ind"
          style={{ width: 100, originX: 0 }}
          initial={false}
          animate={{ x: ind.x, scaleX: ind.w / 100 }}
          transition={reduce ? { duration: 0 } : { duration: 0.26, ease: EASE }}
        />
      )}
      {items.map((t, n) => (
        <button
          key={t.id}
          ref={(el) => { refs.current[t.id] = el; }}
          role="tab"
          aria-selected={t.id === value}
          tabIndex={t.id === value || (!hasValue && n === 0) ? 0 : -1}
          onClick={() => onChange(t.id)}
          className="bs-tab"
        >
          {t.label}
          <span className="bs-tab-n">{t.count}</span>
        </button>
      ))}
    </div>
  );
};

/* ---------- sort + filter popover ---------- */
const Chip: FC<{ name: string; checked: boolean; onPick: () => void; children: ReactNode }> = ({ name, checked, onPick, children }) => (
  <label className="bs-chip">
    <input type="radio" name={name} checked={checked} onChange={onPick} />
    <span>{children}</span>
  </label>
);

// open state, outside-click / Escape close and focus-the-checked-radio, shared by the sort and genre popovers
const usePopover = () => {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const pop = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    pop.current?.querySelector<HTMLInputElement>('input:checked')?.focus();
    const down = (e: PointerEvent) => { if (!wrap.current?.contains(e.target as Node)) setOpen(false); };
    const key = (e: KeyboardEvent) => { if (e.key === 'Escape') { setOpen(false); trigger.current?.focus(); } };
    document.addEventListener('pointerdown', down);
    document.addEventListener('keydown', key);
    return () => { document.removeEventListener('pointerdown', down); document.removeEventListener('keydown', key); };
  }, [open]);
  const onBlur = (e: React.FocusEvent) => { if (e.relatedTarget && !wrap.current?.contains(e.relatedTarget as Node)) setOpen(false); };
  return { open, setOpen, wrap, trigger, pop, onBlur };
};

const GenreMenu: FC<{ items: TabItem[]; value: string; onChange: (id: string) => void }> = ({ items, value, onChange }) => {
  const { open, setOpen, wrap, trigger, pop, onBlur } = usePopover();
  const reduce = useReducedMotion();
    return (
    <div ref={wrap} className="bs-sortwrap" onBlur={onBlur}>
      <button ref={trigger} type="button" className="bs-trigger bs-genre" aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <span className="bs-trigger-label">Genres</span>
        <ChevronDown size={18} strokeWidth={2} aria-hidden className="bs-caret" />
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            ref={pop}
            role="dialog"
            aria-label="Choose a genre"
            className="bs-pop bs-pop-left rp-hide-scroll"
            style={{ transformOrigin: 'top left' }}
            initial={reduce ? { opacity: 0 } : { opacity: 0, scale: 0.96, y: -4 }}
            animate={{ opacity: 1, scale: 1, y: 0, transition: { duration: 0.17, ease: EASE } }}
            exit={{ opacity: 0, scale: 0.97, transition: { duration: 0.12, ease: EASE } }}
          >
            <fieldset onClick={(e) => { if ((e.target as HTMLElement).closest('label')) { setOpen(false); trigger.current?.focus(); } }}>
              <legend>Genre</legend>
              {items.map((g) => (
                <Chip key={g.id} name="bs-genre" checked={g.id === value} onPick={() => onChange(g.id)}>
                  <span className="bs-opt">{g.label}<small>{g.count}</small></span>
                </Chip>
              ))}
            </fieldset>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

const SortMenu: FC<{ sort: SortKey; setSort: (s: SortKey) => void; filters: Filters; setFilters: (f: Filters) => void; hasServices: boolean }> = ({ sort, setSort, filters, setFilters, hasServices }) => {
  const { open, setOpen, wrap, trigger, pop, onBlur } = usePopover();
  const reduce = useReducedMotion();
  const n = activeFilterCount(filters);

  return (
    <div ref={wrap} className="bs-sortwrap" onBlur={onBlur}>
      <button ref={trigger} type="button" className="bs-trigger" aria-haspopup="dialog" aria-expanded={open} aria-label={`Sort and filter, ${SORT_LABELS[sort]}${n ? `, ${n} filter${n > 1 ? 's' : ''} active` : ''}`} onClick={() => setOpen((o) => !o)}>
        <SlidersHorizontal size={16} aria-hidden />
        <span className="bs-trigger-label">{SORT_LABELS[sort]}</span>
        {n > 0 && <span className="bs-badge" aria-label={`${n} filter${n > 1 ? 's' : ''} active`}>{n}</span>}
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            ref={pop}
            role="dialog"
            aria-label="Sort and filter"
            className="bs-pop"
            style={{ transformOrigin: 'top right' }}
            initial={reduce ? { opacity: 0 } : { opacity: 0, scale: 0.96, y: -4 }}
            animate={{ opacity: 1, scale: 1, y: 0, transition: { duration: 0.17, ease: EASE } }}
            exit={{ opacity: 0, scale: 0.97, transition: { duration: 0.12, ease: EASE } }}
          >
            <fieldset>
              <legend>Sort by</legend>
              {(Object.keys(SORT_LABELS) as SortKey[]).map((k) => (
                <Chip key={k} name="bs-sort" checked={sort === k} onPick={() => setSort(k)}>{SORT_LABELS[k]}</Chip>
              ))}
            </fieldset>
            <fieldset>
              <legend>Minimum rating</legend>
              <div className="bs-chips">
                {([[0, 'Any'], [7, '7+'], [8, '8+']] as const).map(([v, l]) => (
                  <Chip key={v} name="bs-rating" checked={filters.minRating === v} onPick={() => setFilters({ ...filters, minRating: v })}>{l}</Chip>
                ))}
              </div>
            </fieldset>
            <fieldset>
              <legend>Recommended within</legend>
              <div className="bs-chips">
                {([[0, 'Any time'], [7, '7 days'], [30, '30 days']] as const).map(([v, l]) => (
                  <Chip key={v} name="bs-within" checked={filters.within === v} onPick={() => setFilters({ ...filters, within: v })}>{l}</Chip>
                ))}
              </div>
            </fieldset>
            {hasServices && (
              <fieldset>
                <legend>Streaming on</legend>
                <div className="bs-chips">
                  {([[false, 'Anything'], [true, 'My services']] as const).map(([v, l]) => (
                    <Chip key={l} name="bs-mine" checked={filters.mine === v} onPick={() => setFilters({ ...filters, mine: v })}>{l}</Chip>
                  ))}
                </div>
              </fieldset>
            )}
            <button type="button" className="bs-clear" disabled={n === 0} onClick={() => setFilters(NO_FILTERS)}>Clear filters</button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

/* ---------- movie card ---------- */
interface CardProps {
  movie: Movie; index: number; onOpen: (m: Movie) => void; onToggle: (id: string) => void; tokens: string[]; match?: Match; grid?: boolean;
}
const MovieCard = memo(function MovieCard({ movie, index, onOpen, onToggle, tokens, match, grid }: CardProps) {
  const [busy, setBusy] = useState(false);
  const reduce = useReducedMotion();
  const li = useRef<HTMLLIElement>(null);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);
  const toggle = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (busy) return;
    setBusy(true);
    const next = ((li.current?.nextElementSibling ?? li.current?.previousElementSibling) as HTMLElement | null)?.querySelector<HTMLElement>('.bs-card');
    timer.current = window.setTimeout(() => { onToggle(movie.id); next?.focus({ preventScroll: true }); }, reduce ? 0 : 320);
  };
  const quick = movie.watched ? 'Move back to unwatched' : 'Mark as watched';
  const n = movie.recommendations.length;
  return (
    <motion.li
      ref={li}
      className="bs-item"
      data-grid={grid || undefined}
      initial={reduce ? false : { opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0, transition: { duration: 0.3, ease: EASE, delay: Math.min(index, 8) * 0.03 } }}
    >
      <button
        type="button"
        className="bs-card"
        onClick={() => onOpen(movie)}
        aria-label={`${movie.title}, ${movie.year}. Rated ${movie.rating.toFixed(1)}. Recommended by ${n} ${n === 1 ? 'creator' : 'creators'}`}
      >
        <span className="bs-lift">
          <span className="bs-poster" style={{ borderRadius: 10 }}>
            <img src={movie.poster} alt={movie.title} loading="lazy" decoding="async" draggable={false} />
            {movie.watched && <span className="bs-watched"><Check size={12} aria-hidden /> Watched</span>}
          </span>
        </span>
        <span className="bs-title"><Hl text={movie.title} tokens={tokens} /></span>
        <span className="bs-sub">{movie.year} · <Star size={11} fill="currentColor" aria-hidden /> {movie.rating.toFixed(1)}</span>
        <Creators movie={movie} />
        {match && match.label !== 'Title' && (
          <span className="bs-match">
            {match.label}: <Hl text={match.text} tokens={tokens} />
          </span>
        )}
        {match && match.label === 'Title' && <span className="bs-match">Title</span>}
      </button>
      <button type="button" tabIndex={-1} className={`bs-quick${busy ? ' is-busy' : ''}`} onClick={toggle} aria-label={`${quick}: ${movie.title}`} title={quick}>
        {busy ? <Check size={16} aria-hidden className="bs-pop-in" /> : movie.watched ? <Undo2 size={16} aria-hidden /> : <Check size={16} aria-hidden />}
      </button>
    </motion.li>
  );
});

/* ---------- shelf ---------- */
const Shelf: FC<{ title: string; count: number; children: ReactNode }> = ({ title, count, children }) => {
  const ref = useRef<HTMLUListElement>(null);
  const [edge, setEdge] = useState({ l: false, r: false });
  const reduce = useReducedMotion();
  const update = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    const l = el.scrollLeft > 4, r = el.scrollLeft + el.clientWidth < el.scrollWidth - 4;
    setEdge((p) => (p.l === l && p.r === r ? p : { l, r }));
  }, []);
  useEffect(update);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [update]);
  const go = (dir: 1 | -1) => ref.current?.scrollBy({ left: dir * ref.current.clientWidth * 0.85, behavior: reduce ? 'auto' : 'smooth' });
  return (
    <section className="bs-shelf" aria-label={title}>
      <h2 className="bs-shelf-h rp-display">{title}<span>{count}</span></h2>
      <div className="bs-shelf-body">
        {edge.l && <button type="button" className="bs-arrow bs-prev" aria-label={`Scroll ${title} back`} onClick={() => go(-1)}><ChevronLeft size={22} aria-hidden /></button>}
        {edge.r && <button type="button" className="bs-arrow bs-next" aria-label={`Scroll ${title} forward`} onClick={() => go(1)}><ChevronRight size={22} aria-hidden /></button>}
        <ul ref={ref} className="bs-row rp-hide-scroll" data-l={edge.l} data-r={edge.r} onScroll={update}>
          {children}
        </ul>
      </div>
    </section>
  );
};

/* ---------- screen ---------- */
interface BrowseProps {
  movies: Movie[]; genres: GenreSummary[]; initialGenre: string; myServices: string[]; account: ReactNode;
  onOpen: (m: Movie) => void; onBack: () => void; onToggleWatched: (id: string) => void;
  backIcon?: 'back' | 'close'; // 'close' (extension): an X after the account slot instead of the back chevron
  strip?: ReactNode; // optional extra controls in the tabs bar, before the sort menu (extension: the "On this site" chips)
}
export const BrowseScreen: FC<BrowseProps> = ({ movies, genres, initialGenre, myServices, account, onOpen, onBack, onToggleWatched, backIcon = 'back', strip }) => {
  const [genre, setGenre] = useState(initialGenre);
  const [status, setStatus] = useState<Status>('unwatched');
  const [sort, setSort] = useState<SortKey>('popular');
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const [query, setQuery] = useState('');
  const input = useRef<HTMLInputElement>(null);

  const tokens = useMemo(() => queryTokens(query), [query]);
  const searching = tokens.length > 0;
  const inGenre = (m: Movie, g: string) => g === ALL_GENRES || m.genres.includes(g);

  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (e.key === '/' && !/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) && !t.isContentEditable && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        input.current?.focus();
      }
    };
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, []);

  const w = status === 'watched';
  const filtered = useMemo(() => filterMovies(movies, filters, myServices), [movies, filters, myServices]);
  const inG = useMemo(() => filtered.filter((m) => inGenre(m, genre)), [filtered, genre]);
  const genreCounts = useMemo(
    () => new Map([ALL_GENRES, ...genres.map((g) => g.name)].map((g) => [g, filtered.filter((m) => m.watched === w && inGenre(m, g)).length])),
    [filtered, w, genres],
  );
  // only the sorted pools depend on `sort`
  const pool = useMemo(() => sortMovies(inG.filter((m) => m.watched === w), sort), [inG, w, sort]);
  const hits = useMemo(() => (searching ? searchMovies(sortMovies(filtered, sort), query) : []), [searching, filtered, sort, query]);
  const counts = useMemo(() => {
    const src = searching ? hits.map((h) => h.movie) : inG;
    return { unwatched: src.filter((m) => !m.watched).length, watched: src.filter((m) => m.watched).length };
  }, [searching, hits, inG]);
  const rawPool = useMemo(() => movies.filter((m) => m.watched === w && inGenre(m, genre)).length, [movies, w, genre]);

  const shelves = useMemo(() => {
    if (searching || !pool.length) return [];
    if (genre === ALL_GENRES) {
      return [{ key: 'top', title: 'Top picks', items: pool.slice(0, TOP_PICKS) }, ...genres.map((g) => ({ key: g.name, title: g.name, items: pool.filter((m) => m.genres.includes(g.name)) })).filter((s) => s.items.length)];
    }
    // consecutive chunks of 8 so each film appears once; a tail under 3 stays with the previous shelf
    const chunks: Movie[][] = [];
    for (let i = 0; i < pool.length; i += 8) chunks.push(pool.slice(i, i + 8));
    if (chunks.length > 1 && chunks[chunks.length - 1].length < 3) chunks[chunks.length - 2].push(...chunks.pop()!);
    return chunks.map((items, i) => ({ key: `s${i}`, title: i === 0 ? `Top picks in ${genre}` : i === 1 ? `More ${genre}` : 'Keep exploring', items }));
  }, [searching, pool, genre, genres]);

  const pickGenre = (g: string) => { setQuery(''); setGenre(g); };
  const clearFilters = () => setFilters(NO_FILTERS);
  const card = (m: Movie, i: number, shelf: string, match?: Match, grid?: boolean) => (
    <MovieCard key={`${shelf}:${m.id}`} movie={m} index={i}
      onOpen={onOpen} onToggle={onToggleWatched} tokens={tokens} match={match} grid={grid} />
  );

  const empty = (() => {
    if (searching) {
      return { h: `No match for “${query.trim()}”`, p: `Nothing in either tab matches. Try a title, an actor, a director, a year or a creator’s handle.${activeFilterCount(filters) ? ' Filters are narrowing the search too.' : ''}`, act: 'Clear search', go: () => setQuery('') };
    }
    if (rawPool > 0) return { h: 'No films match these filters', p: 'Loosen the rating or recency filter to see more.', act: 'Clear filters', go: clearFilters };
    const where = genre === ALL_GENRES ? '' : ` in ${genre}`;
    return status === 'watched'
      ? { h: 'Nothing watched yet', p: `Tap the check on any poster to move it here${where}.` }
      : { h: 'Nothing left to watch', p: `Every pick${where} is marked watched.` };
  })();

  return (
    <div className="bs-root min-h-screen w-full">
      <div className="bs-top">
        <header className="bs-head">
          {backIcon === 'back' && <button type="button" className="bs-back" onClick={onBack} aria-label="Back to genre tiles"><ChevronLeft size={20} aria-hidden /></button>}
          <GenreMenu
            value={genre}
            onChange={pickGenre}
            items={[ALL_GENRES, ...genres.map((g) => g.name)].map((g) => ({ id: g, label: g, count: genreCounts.get(g) ?? 0 }))}
          />
          <span className="bs-word rp-display">Reel<em>Picks</em></span>
          <label className="bs-search">
            <Search size={16} aria-hidden />
            <input
              ref={input}
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Escape') { if (query) setQuery(''); else { e.preventDefault(); input.current?.blur(); } } }}
              placeholder="Search films"
              aria-label="Search films"
              autoComplete="off"
              spellCheck={false}
            />
            {query ? <button type="button" className="bs-x" aria-label="Clear search" onClick={() => { setQuery(''); input.current?.focus(); }}><X size={14} aria-hidden /></button> : <kbd aria-hidden>/</kbd>}
          </label>
          {account}
          {backIcon === 'close' && <button type="button" className="bs-back bs-close" onClick={onBack} aria-label="Close"><X size={20} aria-hidden /></button>}
        </header>
        <div className="bs-bar">
          <h1 className="bs-gtitle rp-display" data-muted={searching || undefined}>{genre}</h1>
          <Tabs
            variant="pill"
            label="Watch status"
            muted={searching}
            value={searching ? '' : status}
            onChange={(s) => { setQuery(''); setStatus(s as Status); }}
            items={[{ id: 'unwatched', label: 'Unwatched', count: counts.unwatched }, { id: 'watched', label: 'Watched', count: counts.watched }]}
          />
          {strip}
          <SortMenu sort={sort} setSort={setSort} filters={filters} setFilters={setFilters} hasServices={myServices.length > 0} />
        </div>
      </div>

      <main className="bs-main">
        {searching && (
          <p className="bs-note" role="status">
            Searching all genres and both tabs · {hits.length} {hits.length === 1 ? 'result' : 'results'}
            <button type="button" onClick={() => setQuery('')}>Clear search</button>
          </p>
        )}
        <div key={searching ? 'search' : `${status}:${genre}`}>
          {searching ? (
            hits.length > 0 && (
              <ul className="bs-grid">
                {hits.map((h, i) => card(h.movie, i, 'search', h.match, true))}
              </ul>
            )
          ) : (
            shelves.map((s) => (
              <Shelf key={s.key} title={s.title} count={s.items.length}>
                {s.items.map((m, i) => card(m, i, s.key))}
              </Shelf>
            ))
          )}
        </div>
        {((searching && !hits.length) || (!searching && !pool.length)) && (
          <div className="bs-empty">
            <h2 className="rp-display">{empty.h}</h2>
            <p>{empty.p}</p>
            {empty.act && <button type="button" onClick={empty.go}>{empty.act}</button>}
          </div>
        )}
      </main>
    </div>
  );
};
