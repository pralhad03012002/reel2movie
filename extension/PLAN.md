# ReelPicks browser extension — build plan

A Chrome extension that puts your ReelPicks list on top of the streaming site you are already on
(Netflix, Prime Video, Hotstar, ...). A floating button opens a full-page overlay: genres, watched and
unwatched tabs, search, sort and filters, posters, and a detail view with description, cast, director,
rating and a Watch now button. "On this site" is on by default, so you see what you saved that is
playing right where you are.

## 1. Decisions

| Question | Decision | Why |
|---|---|---|
| Extension type | Chrome Manifest V3, loaded unpacked for now | Chrome Web Store listing is out of scope. |
| Where the UI runs | An **extension page in an iframe** (`overlay.html`) that a small content script injects over the site | Full CSS isolation from the site (no Shadow DOM and Tailwind v4 problems), and the page's CSP does not apply to extension pages. |
| Reuse | Import the web app's components from `../app/src/components` (Browse, Overlay, tokens, catalog, types) through a Vite alias | One design, one place to fix. Changes to shared components must keep `app/` building. |
| Data | Background service worker reads Firestore over **REST** with the user's ID token. No Firebase SDK in the extension | Small bundle, works in a service worker, security rules still apply (owner-only reads). |
| Sign-in | The user connects once from the **web app**: the extension opens `https://reelpicks-32e42.web.app/?connect=<extensionId>`; after Google sign-in the web app shows "Connect browser extension" and sends `{uid, refreshToken}` with `chrome.runtime.sendMessage` (manifest `externally_connectable`). The extension stores it in `chrome.storage.local` and refreshes ID tokens through `securetoken.googleapis.com` | No Google Cloud OAuth client to create, no Cloud Functions, nothing new to configure for the user. |
| Writes | Only `watched` (the same field the rules already allow) | Keeps the extension a viewer. Add reel, settings and delete stay in the web app. |
| Sites | netflix.com, primevideo.com, amazon.in/amazon.com video pages, hotstar.com, zee5.com, sonyliv.com, tv.apple.com, disneyplus.com, mubi.com, max.com / hbomax.com, hulu.com, crunchyroll.com, sunnxt.com | The services `app/src/lib.js` already knows. Each maps to TMDB provider names by the same patterns. |
| Trailer | Autoplay trailer behind the title like the web app, but only if YouTube embeds play inside the extension page; otherwise the existing "Watch trailer on YouTube" fallback link | An `chrome-extension://` referrer can make YouTube refuse embeds. Verify, do not assume. |
| Look | Same layout as the web app but **neutral**: dark grey panels `#1c1c1f`, white text, light translucent white for selection and hover, no amber accent. Matches the genre dropdown | The user's request. Set by overriding the `--rp-accent*` tokens in the overlay, not by forking components. |
| Closing | Esc, the close button, or a click on the dimmed area outside the panel | Never traps the user on a site. |
| Permissions | `storage`, host permissions for the listed sites plus `firestore.googleapis.com` and `securetoken.googleapis.com`. Nothing else | Least privilege. |

## 2. Architecture

```
OTT page (netflix.com, ...)
  content.ts  ── injects: launcher button + <iframe src=overlay.html?site=netflix>
        │  postMessage (close, open-link)
        ▼
  overlay.html (React, shared components)
        │  chrome.runtime.sendMessage
        ▼
  background.ts (service worker)
        ├─ chrome.storage.local: { uid, refreshToken, idToken, expiresAt, cache: {movies, settings, at} }
        ├─ securetoken REST  → fresh ID token
        └─ Firestore REST    → users/{uid}  (settings: region, services)
                               users/{uid}/movies  (list, paginated)
                               PATCH movies/{id}?updateMask.fieldPaths=watched
web app (reelpicks-32e42.web.app)
  ?connect=<extensionId> → banner "Connect browser extension" → sendMessage(extensionId, {uid, refreshToken})
connect.html (extension page, opened from the launcher when not connected, and as the options page)
  "Connect your ReelPicks account" → opens the web app URL above; shows connected state; Disconnect button
```

Background message API (all replies `{ok:true,...}` or `{ok:false,error}`):
`status` → `{connected, email?}`; `getData` → `{movies, settings, cachedAt}` (cache first, refresh in the
background when older than 5 minutes); `refresh` → forces a fetch; `setWatched {id, watched}` → PATCH;
`disconnect`.

## 3. Subtasks (each: code agent → review agent → fix agent, until clean)

**A. Extension core** (`extension/` scaffold, manifest, background, Firestore REST, connect flow, tests)
- Vite multi-entry build to `extension/dist` (background, content, overlay.html, connect.html), TypeScript, `npm run build`, `npm test`.
- `src/firestore.ts`: typed-value decoder and the list and PATCH calls. `src/auth.ts`: token refresh with expiry margin, one refresh in flight at a time. Unit tests with `node --test` and stubbed fetch.
- `src/sites.ts`: hostname → `{id, label, providerPattern, searchUrl}`. Tests.
- Manifest: MV3, `externally_connectable` for the web app origin, `web_accessible_resources` for `overlay.html` and its assets, only the permissions in section 1.

**B. Overlay UI** (`overlay.html`, content script, design)
- Content script: launcher button (bottom-right, small pill, ReelPicks mark; draggable not needed), iframe overlay with fade and scale-in, focus handling, Esc and outside-click close, restores page scroll and focus on close. Must survive single-page-app navigation (Netflix, Prime) and never inject twice.
- Overlay React app: starts directly in browse (no genre tiles). Shared `BrowseScreen` with the genres dropdown, Unwatched and Watched tabs, search, sort and filters, shelves with posters; shared `MovieOverlay` for details. Extra filter "On {site}" (default on when the site is known) next to "My services". Header has a close (×) button instead of "back".
- Watch now: a link to the current site's search for the title opens in the same tab (`target=_top`); links to other services open a new tab.
- States: loading, not connected (button to connect.html), empty list, "none on this site" (with a button to show everything), offline or error with Retry.
- Look per the table above. Use the Emil Kowalski, Impeccable and Taste skills.

**C. Web app connect step** (`app/`)
- `?connect=<id>` handling: after sign-in show a small panel "Connect browser extension" with a button; on click send `{type:'connect', uid, refreshToken, email}`; show success or the error (extension not installed, wrong id). Remove the `connect` param after use. Does not change anything when the param is absent.

## 4. Test plan

- Unit: Firestore decoder, token refresh, site matching, provider-to-site matching.
- Browser: puppeteer launches Chrome with `--load-extension=dist`, opens a local page that stands in for an OTT site (a dev-only manifest match for `http://127.0.0.1/*`), seeds `chrome.storage.local` with a fake connection and cached movies, and checks: launcher appears once, overlay opens and closes (button, Esc, outside click), filters and search work, "On this site" narrows the list, Watch now URL is right, not-connected and empty states render.
- Real data check: with the temporary-token method already used for the web app, confirm the REST reads return the 95 real movies and the decoder maps them to the same `Movie` shape as the web app. Read-only.
- Visual: screenshots at 1280×800 and 390×844 reviewed against the genre-dropdown look.

## 5. Out of scope

Chrome Web Store packaging, Firefox/Safari, adding reels from the extension, settings editing, live updates (it refreshes on open), picking from OTT-site-specific page content (we do not read or change the site's own page beyond the launcher and the overlay), analytics.

## 6. Risks

- **Site CSP or layout blocks the iframe.** Mitigation: extension iframes are exempt from page CSP; test on a page that sets a strict `frame-src`; fallback to opening `overlay.html` in a new tab from the launcher.
- **Refresh token handling.** Stored only in `chrome.storage.local`, never logged, never sent anywhere but Google's `securetoken` endpoint. Disconnect deletes it.
- **Shared components drift.** `app/` and `extension/` both build in CI-less review: every review pass runs both builds.
- **YouTube embeds in extension pages.** See Trailer row.
