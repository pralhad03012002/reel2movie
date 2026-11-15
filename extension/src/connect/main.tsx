import { StrictMode, useCallback, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import '@app/components/tokens.css';
import '../overlay/index.css';
import { send } from '../shared/bg.ts';

const connectUrl = () => `https://reelpicks-32e42.web.app/?connect=${chrome.runtime.id}`;

const Connect = () => {
  const [st, setSt] = useState<{ connected: boolean; email?: string } | null>(null);
  const check = useCallback(() => send({ type: 'status' }).then((r) => setSt({ connected: !!r.connected, email: r.email })), []);
  useEffect(() => {
    void check();
    const t = setInterval(check, 2000); // flips to Connected once the web app has sent the credentials
    return () => clearInterval(t);
  }, [check]);

  return (
    <div className="rp ext ext-msg">
      <div>
        <h1 className="rp-display text-[28px] font-medium">Reel<em className="opacity-60">Picks</em></h1>
        {st && (st.connected ? (
          <div className="mt-4 space-y-4">
            <p className="text-[15px]">Connected{st.email ? <> as <strong className="font-semibold">{st.email}</strong></> : null}.</p>
            <p className="text-[14px] text-[var(--rp-muted)]">Open a streaming site and press the ReelPicks button, or Alt+Shift+R.</p>
            <button type="button" className="ext-btn ghost" onClick={async () => { await send({ type: 'disconnect' }); void check(); }}>Disconnect</button>
          </div>
        ) : (
          <div className="mt-4 space-y-4">
            <h2 className="text-[18px] font-medium">Connect your ReelPicks account</h2>
            <p className="text-[14px] text-[var(--rp-muted)]">You sign in once on the ReelPicks web app; this page updates by itself when it is done.</p>
            <a className="ext-btn" href={connectUrl()} target="_blank" rel="noopener noreferrer">Connect account</a>
          </div>
        ))}
      </div>
    </div>
  );
};

createRoot(document.getElementById('root')!).render(<StrictMode><Connect /></StrictMode>);
