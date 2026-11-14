import { FC, ReactNode, useMemo } from 'react';
import { ArrowRight } from 'lucide-react';
import type { GenreSummary, Movie } from './types';
import './tokens.css';
import './GenreScreen.css';

export const GenreScreen: FC<{ userName: string; movies: Movie[]; genres: GenreSummary[]; account: ReactNode; empty: ReactNode; onPick: (genre: string) => void; onShowAll: () => void }> = ({ userName, movies, genres, account, empty, onPick, onShowAll }) => {
  const first = userName.trim().split(/\s+/)[0] || 'there';
  // genres arrive sorted by count desc, so genres[0] is the big tile and claims posters first
  const picks = useMemo(() => {
    const used = new Set<string>();
    return genres.map((g, i) => {
      const n = i === 0 ? 5 : 3;
      const own = [...new Set([...g.posters, ...movies.filter((m) => m.genres.includes(g.name)).map((m) => m.poster)])];
      const pics = [...own.filter((p) => !used.has(p)), ...own.filter((p) => used.has(p))].slice(0, n);
      pics.forEach((p) => used.add(p));
      return pics;
    });
  }, [genres, movies]);
  const style = (k: string, v: string | number) => ({ ['--' + k]: v } as React.CSSProperties);

  return (
    <div className="min-h-screen w-full bg-[var(--rp-bg)] text-[var(--rp-text)]">
      <div className="mx-auto w-full max-w-[72rem] px-5 pb-16 pt-10 sm:px-8 sm:pt-14">
        <header className="gn-in flex flex-col gap-6 sm:flex-row sm:items-end sm:justify-between" style={style('i', 0)}>
          <div className="max-w-[36rem]">
            <p className="text-[13px] font-medium uppercase tracking-[0.14em] text-[var(--rp-accent)]">{movies.length ? 'Your picks are ready' : 'Welcome'}</p>
            <h1 className="rp-display mt-3 text-[clamp(2rem,5vw,3.25rem)] font-medium leading-[1.05]">
              What are you in the mood for, <span className="italic">{first}</span>?
            </h1>
            <p className="mt-3 text-[15px] text-[var(--rp-muted)]">Pick a genre to start with. Every other one is a tap away.</p>
          </div>
          <div className="flex shrink-0 items-center gap-3 self-start sm:self-auto">
            {movies.length > 0 && (
              <button type="button" onClick={onShowAll} className="gn-all flex h-12 items-center justify-center gap-2 rounded-full border border-[var(--rp-line-strong)] px-6 text-[15px] font-medium">
                Show all {movies.length}
                <ArrowRight size={16} aria-hidden="true" />
              </button>
            )}
            {account}
          </div>
        </header>

        {!movies.length && <div className="mt-10">{empty}</div>}

        <div className="gn-grid mt-9 sm:mt-12">
          {genres.map((g, idx) => {
            const big = idx === 0;
            const pics = picks[idx];
            const n = pics.length;
            return (
              <button key={g.name} type="button" onClick={() => onPick(g.name)} aria-label={`${g.name}, ${g.count} ${g.count === 1 ? 'pick' : 'picks'}`} className={`gn-tile gn-in${big ? ' gn-big' : ''}`} style={style('i', Math.min(idx + 1, 12))}>
                <span className="gn-pics" aria-hidden="true">
                  {pics.map((src, i) => {
                    const o = i - (n - 1) / 2;
                    return <img key={src + i} src={src} alt="" loading="lazy" draggable={false} className="gn-pic" style={{ ...style('o', o), ...style('a', Math.abs(o) ** 1.5), zIndex: 10 - Math.round(Math.abs(o) * 2) } as React.CSSProperties} />;
                  })}
                </span>
                <span className="gn-txt">
                  <span className={`rp-display block font-medium leading-tight ${big ? 'text-[clamp(1.9rem,3.4vw,2.8rem)]' : 'text-[22px] sm:text-[26px]'}`}>{g.name}</span>
                  <span className="mt-1 block text-[13px] text-[var(--rp-muted)]">{g.count} {g.count === 1 ? 'pick' : 'picks'}</span>
                </span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
};
