# ReelPicks

Share a reel from your phone; the movies and series it recommends appear in your account, on phone
and desktop, each with buttons that open the streaming service that has it.

- `web/` — the installable web app (static files, hosted on Firebase Hosting).
- `worker/` — a Node program that runs on your Mac and does the extraction.
- `PLAN.md` — design, data contract, and what was taken from SaveToList.

How it works: the web app writes the shared link to your account as "queued". The worker picks it
up, downloads the reel's audio and caption (yt-dlp), transcribes it (ElevenLabs), asks Gemini which
titles it recommends, confirms each on TMDB, and saves them to your account. The web app updates
live. Reels shared while the Mac is off wait in the queue.

Supported links: Instagram reels and posts, YouTube Shorts, TikTok videos.

## One-time setup

You need Node 22 or newer.

### 1. Firebase project (free Spark plan)

In the [Firebase console](https://console.firebase.google.com):

1. Create a project. Do not upgrade to Blaze, and ignore "App Hosting" (a different, paid product).
2. **Authentication → Sign-in method → Google → Enable.**
3. **Firestore → Create database** (production mode).
4. **Project Overview → Add app → Web.** Copy the `firebaseConfig` values into
   `web/firebase-config.js`.
5. **Settings → Project settings → Service accounts → Generate new private key.** Save the file as
   `worker/service-account.json`. It grants full access to the project: never share or commit it.

### 2. Keys

```sh
cd worker
cp .env.example .env
```

Fill in `.env`: `TMDB_API_KEY` (either TMDB key form works), `ELEVENLABS_API_KEY`, `GEMINI_API_KEY`
(free from Google AI Studio). Keep keys in `.env` only, never in `.env.example`.

### 3. Install

Still in `worker/`:

```sh
npm install
./setup.sh        # downloads the yt-dlp binary into worker/bin/
```

### Optional: transcribe on your Mac instead of ElevenLabs

The **Settings** switch "Transcribe reels on my computer" makes the worker use local Whisper
(`worker/local_stt.py`, faster-whisper on CPU) instead of ElevenLabs. It needs a Python 3.10-3.13
environment in `worker/.venv` (3.14 has no onnxruntime build for Intel Macs):

```sh
cd worker
python3.12 -m venv .venv          # or: uv venv --python 3.12 .venv
.venv/bin/pip install -r requirements.txt
```

The model downloads into `worker/models/` on first use. The default `small.en` is English-only;
for Hindi or mixed reels set `LOCAL_STT_MODEL=small` and `LOCAL_STT_LANGUAGE=auto` in `.env`.
Audio longer than 3 minutes is rejected on this path.

### 4. Deploy the web app, security rules and index

From the project root, replacing `YOUR_PROJECT_ID`:

```sh
npx firebase-tools login
npx firebase-tools deploy --project YOUR_PROJECT_ID
```

It prints the app's address, `https://YOUR_PROJECT_ID.web.app`.

## Daily use

Start the worker and leave it running:

```sh
cd worker
npm start
```

- **Phone (Android, Chrome):** open the app's address, sign in, then menu → **Add to Home screen /
  Install**. After that, in Instagram tap Share on a reel and pick **ReelPicks**.
- **Desktop:** open the same address, sign in with the same Google account, and paste a reel link.
  The list is the same on both.
- In **Settings** in the app, pick your country and tick the services you subscribe to; those
  buttons are highlighted and "On my services" filters to them.

Streaming buttons open that service's search for the title. On Android this usually opens the
installed app; on desktop, the website.

## Checks

From the project root:

```sh
node --test web/lib.test.js
npm --prefix worker test
```

## Limits

- The worker must be running on the Mac for reels to be processed.
- A reel is tried up to three times, then marked failed.
- Anyone with a Google account who knows the app's address can sign in and queue reels, which uses
  your ElevenLabs and Gemini quota. Keep the address private, or restrict `isOwner()` in
  `firestore.rules` to specific emails.
- Streaming availability comes from TMDB (JustWatch data) and can lag behind the services.
- `web/lib.js` carries a copy of the worker's link rules (`LINKS` in `worker/pipeline.js`); change
  both together.
- To update yt-dlp when downloads start failing, run `./setup.sh` again.
