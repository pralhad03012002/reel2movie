import { useState } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { X } from 'lucide-react';
import './tokens.css';
import { ALL_GENRES } from './types';
import { buildGenres } from './catalog';
import { useReelPicks } from '../useReelPicks';
import { LoginScreen } from './LoginScreen';
import { GenreScreen } from './GenreScreen';
import { BrowseScreen } from './BrowseScreen';
import { MovieOverlay } from './MovieOverlay';
import { AccountMenu, PasteForm } from './AccountMenu';

export const ReelPicks = () => {
  const reduce = useReducedMotion();
  const rp = useReelPicks();
  const [browsing, setBrowsing] = useState(false);
  const [genre, setGenre] = useState(ALL_GENRES);
  const [openId, setOpenId] = useState<string | null>(null);
  const open = rp.movies.find((m) => m.id === openId) ?? null;
  const genres = buildGenres(rp.movies);

  const go = (g?: string) => { if (g) setGenre(g); setBrowsing(!!g); };
  const fade = {
    initial: { opacity: 0, y: reduce ? 0 : 10 },
    animate: { opacity: 1, y: 0 },
    exit: { opacity: 0, y: reduce ? 0 : -6 },
    transition: { duration: 0.24, ease: [0.23, 1, 0.32, 1] as const },
  };

  const account = rp.user && (
    <AccountMenu
      name={rp.user.displayName ?? ''} email={rp.user.email ?? ''} settings={rp.settings} services={rp.allServices} posts={rp.posts}
      onAdd={rp.addReel} onDismiss={rp.dismissPost} onRegion={rp.setRegion} onService={rp.setService} onLocalStt={rp.setLocalStt} onSignOut={rp.signOut}
    />
  );
  const empty = (
    <div className="max-w-[34rem] rounded-2xl border border-[var(--rp-line)] bg-[var(--rp-surface)] p-6">
      <h2 className="rp-display text-[22px] font-medium">No picks yet</h2>
      <p className="mb-5 mt-2 text-[14.5px] leading-relaxed text-[var(--rp-muted)]">
        On Android, install this app from the browser menu (Add to Home screen), then tap Share on an Instagram reel and choose ReelPicks. On a computer, paste a reel link here.
      </p>
      <PasteForm onAdd={rp.addReel} />
    </div>
  );

  const screen = rp.user === undefined || (rp.user && !rp.loaded) ? 'wait' : !rp.user ? 'login' : browsing ? 'browse' : 'genres';

  return (
    <div className="rp relative min-h-screen w-full overflow-x-hidden">
      <AnimatePresence mode="wait" initial={false}>
        {screen === 'login' && (
          <motion.div key="login" {...fade}>
            <LoginScreen onSignIn={rp.signIn} error={rp.message} />
          </motion.div>
        )}
        {screen === 'genres' && (
          <motion.div key="genres" {...fade}>
            <GenreScreen
              userName={rp.user?.displayName ?? ''} movies={rp.movies} genres={genres} account={account} empty={empty}
              onPick={(g) => go(g)} onShowAll={() => go(ALL_GENRES)}
            />
          </motion.div>
        )}
        {screen === 'browse' && (
          <motion.div key="browse" {...fade}>
            <BrowseScreen
              movies={rp.movies} genres={genres} initialGenre={genre} myServices={rp.settings.services} account={account}
              onOpen={(m) => setOpenId(m.id)} onBack={() => go()} onToggleWatched={rp.toggleWatched}
            />
          </motion.div>
        )}
      </AnimatePresence>
      <AnimatePresence>
        {open && (
          <MovieOverlay key={open.id} movie={open} myServices={rp.settings.services} onClose={() => setOpenId(null)} onToggleWatched={rp.toggleWatched} onRemove={rp.removeMovie} />
        )}
      </AnimatePresence>
      {rp.message && screen !== 'login' && (
        <div role="status" className="fixed bottom-4 left-1/2 z-[60] flex w-[min(30rem,calc(100vw-32px))] -translate-x-1/2 items-start gap-3 rounded-xl border border-[var(--rp-line-strong)] bg-[#1c1c1f] py-3 pl-4 pr-2 text-[13.5px] shadow-[0_16px_40px_-8px_rgb(0_0_0/0.7)]">
          <p className="flex-1 pt-1 leading-snug">{rp.message}</p>
          <button type="button" aria-label="Dismiss message" onClick={() => rp.setMessage('')} className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[var(--rp-muted)] hover:bg-white/[0.08]"><X size={16} aria-hidden /></button>
        </div>
      )}
    </div>
  );
};
