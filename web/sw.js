// Registered only so browsers that still want a service worker treat the app as installable.
// ponytail: no caching, so the app needs a connection (Firestore does too); add a cache if offline use matters.
self.addEventListener('install', () => self.skipWaiting());
