// Connection (uid + refresh token) kept in storage; hands out a valid ID token, refreshing through securetoken.googleapis.com.
import { firebaseConfig } from '../../app/src/firebase-config.js'; // public identifiers, not secrets

export interface Connection { uid: string; email: string; refreshToken: string; idToken: string; expiresAt: number }
export interface Store { get(): Promise<Connection | null>; set(c: Connection): Promise<void>; clear(): Promise<void> }

export class NotConnected extends Error { constructor() { super('Not connected'); this.name = 'NotConnected'; } }
export class BadConnection extends Error { constructor() { super('The sign-in was rejected'); this.name = 'BadConnection'; } }

const MARGIN_MS = 60_000;
const DEAD = ['TOKEN_EXPIRED', 'INVALID_REFRESH_TOKEN', 'USER_NOT_FOUND', 'USER_DISABLED']; // the refresh token will never work again

export function createAuth({ store, fetch: f = fetch, now = Date.now }: { store: Store; fetch?: typeof fetch; now?: () => number }) {
  // Exchanges a refresh token. Throws BadConnection if Google says it is dead; other failures are plain Errors (retryable).
  async function exchange(refreshToken: string) {
    const res = await f(`https://securetoken.googleapis.com/v1/token?key=${firebaseConfig.apiKey}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ grant_type: 'refresh_token', refresh_token: refreshToken }),
    });
    if (!res.ok) {
      const msg = String((await res.json().catch(() => null))?.error?.message ?? '');
      if (res.status === 400 && DEAD.some((d) => msg.startsWith(d))) throw new BadConnection();
      throw new Error(`Token refresh failed (${res.status})`);
    }
    const b = await res.json();
    return { idToken: String(b.id_token), refreshToken: String(b.refresh_token || refreshToken), expiresAt: now() + Number(b.expires_in) * 1000, uid: String(b.user_id) };
  }

  // Bumped on connect/disconnect: a refresh that started under an older generation must not write its tokens back.
  let gen = 0;
  let inflight: Promise<Connection> | null = null;
  const refresh = (c: Connection) => (inflight ??= (async () => {
    const g = gen;
    try {
      const t = await exchange(c.refreshToken);
      if (g !== gen) throw new NotConnected(); // disconnected or reconnected meanwhile
      const next = { ...c, idToken: t.idToken, refreshToken: t.refreshToken, expiresAt: t.expiresAt };
      await store.set(next);
      return next;
    } catch (e) {
      if (e instanceof BadConnection && g === gen) { await store.clear(); throw new NotConnected(); }
      throw e;
    } finally { if (g === gen) inflight = null; } // after a bump, inflight already belongs to someone else
  })());

  return {
    store,
    async connection(): Promise<Connection> {
      const c = await store.get();
      if (!c) throw new NotConnected();
      return c;
    },
    /** A token with at least 60 s left. */
    async getIdToken(): Promise<{ uid: string; idToken: string }> {
      const c = await this.connection();
      const fresh = c.expiresAt - now() > MARGIN_MS ? c : await refresh(c);
      return { uid: fresh.uid, idToken: fresh.idToken };
    },
    /** Verifies a refresh token from the web app (one exchange, uid must match) and only then saves it. */
    async connect(uid: string, email: string, refreshToken: string): Promise<void> {
      const t = await exchange(refreshToken);
      if (t.uid !== uid) throw new BadConnection();
      gen++; inflight = null; // no await between this and set: refreshes of the previous connection are now void
      await store.set({ uid, email, refreshToken: t.refreshToken, idToken: t.idToken, expiresAt: t.expiresAt });
    },
    async disconnect(): Promise<void> {
      gen++; inflight = null;
      await store.clear();
    },
  };
}
