// ReelPicks worker: watches Firestore for queued posts and runs the pipeline on each.
// Run: npm start   (node --env-file=.env index.js)
import { initializeApp } from "firebase-admin/app";
import { FieldValue, getFirestore } from "firebase-admin/firestore";
import { accessSync, constants } from "node:fs";
import { setTimeout as sleep } from "node:timers/promises";
import { processReel, YT_DLP } from "./pipeline.js";

for (const k of ["TMDB_API_KEY", "ELEVENLABS_API_KEY", "GEMINI_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS"])
  if (!process.env[k]) throw new Error(`${k} is not set (see .env.example)`);
try {
  accessSync(YT_DLP, constants.X_OK);
} catch {
  throw new Error(`${YT_DLP} is missing or not executable: run ./setup.sh`);
}

initializeApp(); // reads GOOGLE_APPLICATION_CREDENTIALS
const db = getFirestore();
const posts = db.collectionGroup("processingPosts");
const now = FieldValue.serverTimestamp;
const MAX_ATTEMPTS = 3;

async function handle(ref) {
  // Claim: queued -> processing in a transaction, so a post is never processed twice.
  // A post that keeps crashing the worker is re-queued at each startup; attempts stops that loop.
  const post = await db.runTransaction(async (tx) => {
    const post = (await tx.get(ref)).data();
    if (post?.status !== "queued") return null;
    const attempts = (post.attempts ?? 0) + 1;
    if (attempts > MAX_ATTEMPTS) {
      tx.update(ref, { status: "failed", error: `Gave up after ${MAX_ATTEMPTS} attempts`, updatedAt: now() });
      return null;
    }
    tx.update(ref, { status: "processing", stage: "downloading", attempts, updatedAt: now() });
    return post;
  });
  if (!post) return;
  console.log(`${ref.path}: processing`);

  try {
    const localStt = (await ref.parent.parent.get()).get("localStt") === true; // the user's Settings switch
    console.log(`${ref.path}: transcribing with ${localStt ? "local Whisper" : "ElevenLabs"}`);
    const { creatorHandle, movies } = await processReel(post.url, {
      fetch,
      env: process.env,
      localStt,
      // "transcribing-local" lets the app show which path ran
      onStage: (stage) => ref.update({ stage: localStt && stage === "transcribing" ? "transcribing-local" : stage, updatedAt: now() }),
    });
    if (!movies.length) throw new Error("No movie or series found in this reel");

    const moviesCol = ref.parent.parent.collection("movies");
    for (const movie of movies) {
      const id = `${movie.mediaType}_${movie.tmdbId}`;
      const { watched, sources, ...fresh } = movie;
      await db.runTransaction(async (tx) => {
        const movieRef = moviesCol.doc(id);
        const old = await tx.get(movieRef);
        // Existing doc: refresh TMDB fields, append the source, leave watched and createdAt alone.
        // update() rather than set(merge) so the providers map is replaced, not deep-merged with stale services.
        if (old.exists) {
          const seen = (old.get("sources") ?? []).some((s) => s.postUrl === sources[0].postUrl); // same reel shared again
          tx.update(movieRef, { ...fresh, ...(!seen && { sources: FieldValue.arrayUnion(...sources) }), updatedAt: now() });
        } else tx.set(movieRef, { ...movie, createdAt: now(), updatedAt: now() });
      });
    }
    await ref.update({ status: "done", updatedAt: now(), ...(creatorHandle && { creatorHandle }) });
    console.log(`${ref.path}: done, ${movies.length} title(s)`);
  } catch (e) {
    const timedOut = e?.name === "TimeoutError" || e?.name === "AbortError"; // processReel's deadline
    const error = timedOut ? "Timed out" : String(e?.message ?? e).slice(0, 200);
    // A network failure, timeout, rate limit or overloaded service is worth another go: back to the queue, while attempts last.
    const retry = (timedOut || / (unreachable|error (429|5\d\d))$/.test(error)) && (post.attempts ?? 0) + 1 < MAX_ATTEMPTS;
    console.error(`${ref.path}: ${retry ? "will retry" : "failed"}: ${error}`);
    // ponytail: the wait holds the whole queue so a dead network cannot burn the attempts in seconds. Re-queue from a timer if that bites.
    if (retry) await sleep(60_000);
    await ref.update({ ...(retry ? { status: "queued" } : { status: "failed", error }), updatedAt: now() })
      .catch((e2) => console.error(e2.message));
  }
}

// Error 9 FAILED_PRECONDITION naming an index: the collection-group index is missing or still building.
function exitIfIndexBuilding(e) {
  if (e?.code !== 9 || !/index/i.test(e.message)) return;
  console.error("Firestore index is still building; wait a few minutes and start again, or run `npx firebase-tools deploy --only firestore:indexes`");
  process.exit(1);
}

// Single instance by design, so anything still "processing" at startup was orphaned by a previous
// run: put it back in the queue. In a transaction, so a status written meanwhile is not clobbered.
const orphans = await posts.where("status", "==", "processing").get().catch((e) => {
  exitIfIndexBuilding(e);
  throw e;
});
for (const { ref } of orphans.docs)
  await db.runTransaction(async (tx) => {
    if ((await tx.get(ref)).get("status") !== "processing") return;
    console.log(`${ref.path}: orphaned, re-queueing`);
    tx.update(ref, { status: "queued", updatedAt: now() });
  });

// ponytail: one post at a time through a promise chain. Fine for one person's shares; run handle() in a small pool if the queue backs up.
let chain = Promise.resolve();
posts.where("status", "==", "queued").onSnapshot(
  (snap) => {
    for (const change of snap.docChanges())
      if (change.type !== "removed") // "modified" too: a re-queue the listener saw in one snapshot with its claim
        chain = chain.then(() => handle(change.doc.ref)).catch((e) => console.error(`${change.doc.ref.path}: ${e.message}`));
  },
  (e) => {
    exitIfIndexBuilding(e);
    console.error(`Firestore listener failed: ${e.message}`);
    process.exit(1);
  },
);
console.log("ReelPicks worker listening for queued posts. Ctrl+C to stop.");
