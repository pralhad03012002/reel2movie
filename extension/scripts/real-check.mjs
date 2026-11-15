// Read-only check against the real project (not run in CI). Needs Node 22.18+/24 and worker/service-account.json.
// Prints counts and field names only, never titles, tokens, emails or uids.
//   node scripts/real-check.mjs
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { firebaseConfig } from '../../app/src/firebase-config.js';
import { createAuth } from '../src/auth.ts';
import { getSettings, listMovies } from '../src/firestore.ts';
import { toMovie } from '../../app/src/movie.ts';

const workerDir = fileURLToPath(new URL('../../worker/', import.meta.url));
const require = createRequire(workerDir);
const { initializeApp, cert } = require('firebase-admin/app');
const { getAuth } = require('firebase-admin/auth');
initializeApp({ credential: cert(workerDir + 'service-account.json') });
const admin = getAuth();
const uid = (await admin.listUsers(1)).users[0].uid;

const res = await fetch(`https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken?key=${firebaseConfig.apiKey}`, {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ token: await admin.createCustomToken(uid), returnSecureToken: true }),
});
if (!res.ok) throw new Error(`signInWithCustomToken failed (${res.status})`);
const t = await res.json();

let stored = { uid, email: '', refreshToken: t.refreshToken, idToken: t.idToken, expiresAt: 0 }; // expired on purpose: forces a refresh
const auth = createAuth({ store: { get: async () => stored, set: async (c) => { stored = c; }, clear: async () => { stored = null; } } });
const { uid: u, idToken } = await auth.getIdToken();
console.log('refresh ok:', !!stored && stored.expiresAt > Date.now());

const raws = await listMovies(u, idToken);
const settings = await getSettings(u, idToken);
const movies = raws.map((r) => toMovie(r.data, r.id, settings.region));
console.log('movies:', raws.length);
console.log('settings keys:', Object.keys(settings).join(','), '| region:', settings.region, '| services:', settings.services.length);
console.log('raw doc fields:', [...new Set(raws.flatMap((r) => Object.keys(r.data)))].sort().join(','));
console.log('with title:', movies.filter((m) => m.title).length, '| with poster:', movies.filter((m) => m.poster).length,
  '| with providers:', movies.filter((m) => m.providers.length).length, '| with recommendations:', movies.filter((m) => m.recommendations.length).length);
