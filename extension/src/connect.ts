// Validation of the one external message the web app may send: { type:'connect', uid, refreshToken, email }.
export const WEB_ORIGIN = 'https://reelpicks-32e42.web.app';

export interface ConnectMsg { type: 'connect'; uid: string; refreshToken: string; email: string }

const str = (v: unknown, max: number): v is string => typeof v === 'string' && v.length > 0 && v.length <= max;

/** Returns the clean message, or null if the sender or the shape is wrong. */
export function parseConnect(msg: unknown, sender: { origin?: string; url?: string }): ConnectMsg | null {
  let origin = sender.origin;
  if (!origin && sender.url) try { origin = new URL(sender.url).origin; } catch { /* leave undefined */ }
  if (origin !== WEB_ORIGIN) return null;
  const m = msg as Record<string, unknown> | null;
  if (!m || typeof m !== 'object' || m.type !== 'connect') return null;
  const email = m.email ?? '';
  if (!str(m.uid, 128) || !str(m.refreshToken, 4096) || typeof email !== 'string' || email.length > 320) return null;
  return { type: 'connect', uid: m.uid, refreshToken: m.refreshToken, email };
}
