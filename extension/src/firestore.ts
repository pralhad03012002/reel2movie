// Firestore REST: typed-value decoder, movie list, settings, and the one write (`watched`). Reads need the owner's ID token.
import { firebaseConfig } from '../../app/src/firebase-config.js'; // public identifiers, not secrets

const BASE = `https://firestore.googleapis.com/v1/projects/${firebaseConfig.projectId}/databases/(default)/documents`;

export interface Settings { region: string; services: string[]; localStt: boolean }
export interface RawMovie { id: string; data: Record<string, any> }

// Firestore typed JSON -> plain JS. integerValue arrives as a string; timestampValue stays an ISO string.
export function decodeValue(v: Record<string, any>): any {
  if ('stringValue' in v) return v.stringValue;
  if ('integerValue' in v) return Number(v.integerValue);
  if ('doubleValue' in v) return v.doubleValue;
  if ('booleanValue' in v) return v.booleanValue;
  if ('nullValue' in v) return null;
  if ('timestampValue' in v) return v.timestampValue;
  if ('arrayValue' in v) return (v.arrayValue.values ?? []).map(decodeValue);
  if ('mapValue' in v) return decodeFields(v.mapValue.fields);
  return null; // bytes, geoPoint, reference: not used by this app
}
export const decodeFields = (fields: Record<string, any> = {}): Record<string, any> =>
  Object.fromEntries(Object.entries(fields).map(([k, v]) => [k, decodeValue(v)]));

type Fetch = typeof fetch;
const authInit = (idToken: string, init: RequestInit = {}): RequestInit => ({ ...init, headers: { ...init.headers, Authorization: `Bearer ${idToken}` } });
// The message carries only the status, never the URL (it can hold the uid) or the token.
const fail = (status: number) => new Error(`Firestore request failed (${status})`);

export async function listMovies(uid: string, idToken: string, f: Fetch = fetch): Promise<RawMovie[]> {
  const out: RawMovie[] = [];
  let pageToken = '';
  do {
    const res = await f(`${BASE}/users/${encodeURIComponent(uid)}/movies?pageSize=300${pageToken ? `&pageToken=${encodeURIComponent(pageToken)}` : ''}`, authInit(idToken));
    if (!res.ok) throw fail(res.status);
    const body = await res.json();
    for (const d of body.documents ?? []) out.push({ id: String(d.name).split('/').pop()!, data: decodeFields(d.fields) });
    pageToken = body.nextPageToken ?? '';
  } while (pageToken);
  // newest first, like the web app (ISO timestamps compare as strings)
  return out.sort((a, b) => String(b.data.updatedAt ?? '9').localeCompare(String(a.data.updatedAt ?? '9')));
}

export async function getSettings(uid: string, idToken: string, f: Fetch = fetch): Promise<Settings> {
  const defaults: Settings = { region: 'IN', services: [], localStt: false };
  const res = await f(`${BASE}/users/${encodeURIComponent(uid)}`, authInit(idToken));
  if (res.status === 404) return defaults;
  if (!res.ok) throw fail(res.status);
  return { ...defaults, ...decodeFields((await res.json()).fields) };
}

export async function setWatched(uid: string, idToken: string, id: string, watched: boolean, f: Fetch = fetch): Promise<void> {
  const url = `${BASE}/users/${encodeURIComponent(uid)}/movies/${encodeURIComponent(id)}?updateMask.fieldPaths=watched&currentDocument.exists=true`;
  const res = await f(url, authInit(idToken, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ fields: { watched: { booleanValue: watched } } }) }));
  if (!res.ok) throw fail(res.status);
}
