import { FC, useMemo, useState } from 'react';
import './tokens.css';
import './LoginScreen.css';

const Mark: FC = () => (
  <svg width="30" height="30" viewBox="0 0 32 32" aria-hidden="true">
    <path d="M7 3h18a2 2 0 0 1 2 2v23.2a.8.8 0 0 1-1.3.6L16 21.5l-9.7 7.3A.8.8 0 0 1 5 28.2V5a2 2 0 0 1 2-2z" fill="var(--rp-accent)" />
    <path d="M13 9.5v7.5l6.2-3.75z" fill="var(--rp-accent-ink)" />
  </svg>
);

const GoogleG: FC = () => (
  <svg width="20" height="20" viewBox="0 0 48 48" aria-hidden="true">
    <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9.1 3.6l6.8-6.8C35.8 2.4 30.3 0 24 0 14.6 0 6.5 5.4 2.6 13.2l7.9 6.1C12.4 13.6 17.7 9.5 24 9.5z" />
    <path fill="#4285F4" d="M46.5 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.7c-.6 3-2.3 5.4-4.8 7.1l7.6 5.9c4.4-4.1 7-10.1 7-17.5z" />
    <path fill="#FBBC05" d="M10.5 28.7a14.5 14.5 0 0 1 0-9.4l-7.9-6.1a24 24 0 0 0 0 21.6l7.9-6.1z" />
    <path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.6-5.9c-2.1 1.4-4.9 2.3-8.3 2.3-6.3 0-11.6-4.1-13.5-9.8l-7.9 6.1C6.5 42.6 14.6 48 24 48z" />
  </svg>
);

// Shown before sign-in, when there is no account data yet: a fixed wall of posters shipped with the app.
const WALL = 'movie_1124 movie_117691 movie_120 movie_120467 movie_129 movie_138843 movie_1417 movie_146233 movie_155 movie_157336 movie_20453 movie_244786 movie_27205 movie_313369 movie_324857 movie_352173 movie_354912 movie_360814 movie_372058 movie_419430 movie_438631 movie_493922 movie_496243 movie_538858'.split(' ');

export const LoginScreen: FC<{ onSignIn: () => Promise<unknown>; error?: string }> = ({ onSignIn, error }) => {
  const [loading, setLoading] = useState(false);

  const cols = useMemo(() => {
    const p = WALL.map((id) => `${import.meta.env.BASE_URL}wall/${id}.jpg`);
    return [70, 98, 126, 84, 112, 90].map((d, c) => ({ list: p.filter((_, i) => i % 6 === c), d }));
  }, []);

  const go = async () => {
    setLoading(true);
    await onSignIn();
    setLoading(false);
  };

  return (
    <div className="relative min-h-screen w-full overflow-hidden bg-[var(--rp-bg)] text-[var(--rp-text)]">
      <div className="lg-wall" aria-hidden="true">
        {cols.map((c, i) => (
          <div key={i} className="lg-col" style={{ ['--d' as string]: `${c.d}s` }}>
            {[...c.list, ...c.list].map((src, j) => (
              <img key={j} src={src} alt="" loading="lazy" draggable={false} />
            ))}
          </div>
        ))}
      </div>
      <div className="absolute inset-0" style={{ background: 'radial-gradient(ellipse 70% 60% at 50% 55%, rgb(10 10 12 / .92) 0%, rgb(10 10 12 / .7) 55%, rgb(10 10 12 / .35) 100%), linear-gradient(to bottom, rgb(10 10 12 / .7), transparent 25%, transparent 70%, #0a0a0c)' }} />

      <main className="relative z-10 mx-auto flex min-h-screen w-full max-w-[34rem] flex-col items-center justify-center px-6 py-16 text-center">
        <div className="lg-in flex items-center gap-2.5" style={{ ['--i' as string]: 0 }}>
          <Mark />
          <span className="rp-display text-[28px] font-semibold tracking-tight">Reel<span className="italic font-normal text-[var(--rp-accent)]">Picks</span></span>
        </div>
        <h1 className="lg-in rp-display mt-9 text-[clamp(2.1rem,6vw,3.4rem)] font-medium leading-[1.06]" style={{ ['--i' as string]: 1 }}>
          Every movie a reel <span className="italic">sold you</span>, in one list.
        </h1>
        <p className="lg-in mt-5 max-w-[27rem] text-[16px] leading-relaxed text-[var(--rp-muted)]" style={{ ['--i' as string]: 2 }}>
          The reels you save become a watchlist. Tap a title and it opens straight in the streaming app that has it.
        </p>
        <div className="lg-in mt-10 w-full max-w-[21rem]" style={{ ['--i' as string]: 3 }}>
          <button
            type="button"
            onClick={go}
            disabled={loading}
            aria-busy={loading}
            className="lg-btn flex h-[52px] w-full items-center justify-center gap-3 rounded-full bg-[#f5f2ea] text-[15px] font-semibold"
          >
            {loading ? (
              <>
                <span className="lg-spin block h-[18px] w-[18px] rounded-full border-2 border-current/25 border-t-current" />
                Signing in
              </>
            ) : (
              <>
                <GoogleG />
                Continue with Google
              </>
            )}
          </button>
          {loading && <span role="status" className="sr-only">Signing in</span>}
          {error && <p role="alert" className="mt-4 text-[13px] leading-snug text-[var(--rp-danger)]">{error}</p>}
        </div>
        <p className="lg-in mt-6 max-w-[20rem] text-[12.5px] leading-relaxed text-[var(--rp-muted)]" style={{ ['--i' as string]: 4 }}>
          We only read your name and email to keep your list. Nothing is posted to Google or Instagram.
        </p>
      </main>
    </div>
  );
};
