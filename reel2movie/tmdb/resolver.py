"""Ties the TMDB client + scoring together to resolve a single candidate."""

from __future__ import annotations

import json
import logging
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import requests

from reel2movie.core.models import Candidate, ResolvedMovie, TMDBSearchResult
from reel2movie.core.protocols import TMDBClient
from reel2movie.text_extraction.claude_code_extractor import TextChatClient
from reel2movie.tmdb.scoring import find_exact_matches, pick_best, score_result

logger = logging.getLogger(__name__)

# Backoff schedule for `resolve_candidate_with_retry`'s retry loop: starts
# at 1s, doubles each attempt, capped at 30s -- deliberately not
# configurable beyond `deadline_seconds` (see its docstring), this doesn't
# need to be clever.
_RETRY_INITIAL_BACKOFF_SECONDS = 1.0
_RETRY_MAX_BACKOFF_SECONDS = 30.0

# Exceptions `resolve_candidate_with_retry` retries the WHOLE
# `resolve_candidate()` call for. Connection/timeout errors can surface
# here even though `tmdb/client.py`'s `TMDBHttpClient.search()` already
# retries those internally (3 attempts) -- its budget can still be
# exhausted under sustained TMDB flakiness, in which case the final
# exception propagates up through `resolve_candidate()` to here.
# `requests.exceptions.HTTPError` (a real 4xx/5xx response) is
# deliberately included here even though `client.search()` never retries
# it itself (a real API-level error response isn't a transient connection
# issue at that layer) -- this OUTER retry loop is specifically meant to
# also cover that case, per this subtask's spec, since a transient 429/5xx
# from TMDB is still worth retrying from scratch at this higher level.
# `_is_retryable_http_error` below further narrows WHICH `HTTPError`s
# actually qualify -- see that function's docstring.
_RETRYABLE_EXCEPTIONS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.HTTPError,
)

# HTTP status codes worth retrying an `HTTPError` for: 429 (rate limited)
# and any 5xx (server-side issue) are plausibly transient. Anything else
# (401 invalid/expired token, 400, 403, 404, ...) is a real, permanent
# response that will never succeed no matter how many times it's retried
# -- e.g. an expired TMDB token would otherwise make
# `resolve_candidate_with_retry` burn its full `deadline_seconds` (5
# minutes by default) retrying a 401 for every single candidate, turning
# a config error into a multi-minute hang instead of an immediate,
# diagnosable failure.
_RETRYABLE_HTTP_STATUS_MIN = 500


def _is_retryable_http_error(exc: requests.exceptions.HTTPError) -> bool:
    """Whether `exc` (one of `_RETRYABLE_EXCEPTIONS`) is actually worth
    retrying -- only ever `False` for an `HTTPError` with a real,
    non-transient status code; every other `_RETRYABLE_EXCEPTIONS` member
    (`ConnectionError`/`Timeout`) is always retryable, same as before this
    check existed.

    An `HTTPError` whose `.response` is `None` (unusual -- `requests`
    normally always attaches the response that triggered
    `raise_for_status()`) is treated as NOT retryable: with no status
    code to inspect, there's no basis for believing it's transient, and
    the safer default is to fail fast rather than burn the retry budget
    on an unknown.
    """
    response = exc.response
    if response is None:
        return False
    return response.status_code == 429 or response.status_code >= _RETRYABLE_HTTP_STATUS_MIN

_YEAR_IN_PARENS = re.compile(r"\((\d{4})\)")
_TRAILING_YEAR_IN_PARENS = re.compile(r"\s*\((\d{4})\)\s*$")

_DISAMBIGUATION_PROMPT_TEMPLATE = """Several different movies/TV shows in a database share the exact same \
title, and we need to figure out which one a piece of surrounding text is \
actually describing or recommending.

Surrounding text (e.g. a social media caption or comment):
\"\"\"
{context}
\"\"\"

Candidates (each a distinct entry that shares the same title):
{candidates}

Based ONLY on how well each candidate's "overview" matches what the \
surrounding text is actually describing or recommending, which candidate \
is it? Respond with ONLY that candidate's "id" as a bare integer, and \
nothing else -- no prose, no punctuation, no markdown.

IMPORTANT -- read before answering: if NONE of the candidates' overviews \
plausibly describe what the surrounding text is actually about, you MUST \
respond with exactly the string "unknown" instead of guessing. These \
candidates may include entirely unrelated works -- in some real cases, \
one has been an unrelated, inappropriate (e.g. adult-themed) title that \
merely happens to share the exact same name. Guessing wrong here is worse \
than admitting you don't know: only name an id when you are genuinely \
confident, from the text, that THIS SPECIFIC candidate's overview -- not \
just "some movie/show with this title" -- is the one being described.
"""

# How many independent samples `disambiguate_with_context` asks the chat
# client for the SAME tie-break prompt, to counteract a single
# non-deterministic LLM call occasionally picking a wrong (sometimes
# inappropriate) entry -- see PROGRESS.md's "Don't Be Shy" case: across 8
# real live trials of a single-sample ask, the model picked a wrong entry
# 1/8 times (once landing on an adult-themed title sharing the same exact
# title as the real, intended recommendation) and never once replied
# "unknown", even when no candidate's overview plausibly matched. Scoped
# NARROWLY to this one tie-break call (not every chat-client call in this
# codebase): this is the one place a single wrong guess has outsized harm
# (surfacing an inappropriate/unrelated result to the user is worse than
# just being unresolved), so it alone is worth the extra cost. Real cost
# tradeoff: this triples the chat-client calls for this ONE disambiguation
# scenario -- which only fires when 2+ exact-title TMDB matches exist for
# a given candidate (a comparatively rare case; most candidates resolve
# with 0-1 exact matches and never reach this function at all), not for
# every TMDB resolution in the pipeline.
_DISAMBIGUATION_SAMPLE_COUNT = 3

# Minimum number of the `_DISAMBIGUATION_SAMPLE_COUNT` samples that must
# agree on the same candidate id before that id is trusted. 2-of-3 is a
# bare majority, not unanimous consent: requiring all 3 to agree would
# make the tie-break nearly as fragile as a single sample whenever the
# model is even slightly inconsistent across calls, while 2-of-3 is
# already strong evidence against a one-off bad sample. With exactly 3
# samples, at most one id can ever reach this threshold (two different ids
# both reaching 2 would require 4 votes), so the result is never
# ambiguous between competing majorities.
_DISAMBIGUATION_MAJORITY_THRESHOLD = 2


def _find_by_id(
    candidates: list[TMDBSearchResult], candidate_id: int
) -> TMDBSearchResult | None:
    """Linear lookup of `candidate_id` among `candidates` -- shared by
    `_disambiguate_once` (validating a reply's id) and
    `disambiguate_with_context` (resolving the winning majority id back to
    its `TMDBSearchResult`), instead of duplicating the same loop twice.
    """
    for candidate in candidates:
        if candidate.id == candidate_id:
            return candidate
    return None


def _disambiguate_once(
    candidates: list[TMDBSearchResult], context: str, chat_client: TextChatClient
) -> int | None:
    """One single, non-deterministic sample of the disambiguation prompt.

    Returns the picked candidate's `id`, or `None` for every "inconclusive
    this sample" outcome: a chat-client exception, the literal "unknown"
    reply, a reply that isn't a bare integer, or an id that isn't actually
    among `candidates`. Never raises.

    Factored out of `disambiguate_with_context` purely so that function
    can call this `_DISAMBIGUATION_SAMPLE_COUNT` times and vote across the
    results (see that constant's docstring) -- this is the part that's
    actually repeated; the majority-counting logic lives in the caller.
    """
    payload = [
        {
            "id": c.id,
            "title": c.title,
            "year": c.year,
            "media_type": c.media_type,
            "overview": c.overview,
        }
        for c in candidates
    ]
    prompt = _DISAMBIGUATION_PROMPT_TEMPLATE.format(
        context=context, candidates=json.dumps(payload, indent=2)
    )

    try:
        raw_reply = chat_client.chat(prompt)
    except Exception:
        logger.exception(
            "disambiguation chat call failed; treating this sample as inconclusive"
        )
        return None

    reply = raw_reply.strip()
    if reply.lower() == "unknown":
        return None

    try:
        picked_id = int(reply)
    except ValueError:
        logger.warning(
            "disambiguation reply was neither a bare integer nor "
            "'unknown', treating this sample as inconclusive: %r",
            raw_reply,
        )
        return None

    if _find_by_id(candidates, picked_id) is not None:
        return picked_id

    logger.warning(
        "disambiguation picked id %r, which is not among the candidate "
        "ids %r; treating this sample as inconclusive",
        picked_id,
        [c.id for c in candidates],
    )
    return None


def disambiguate_with_context(
    candidates: list[TMDBSearchResult], context: str, chat_client: TextChatClient
) -> TMDBSearchResult | None:
    """Pick the right one among tied exact-title matches using surrounding
    text (e.g. the reel's caption) compared against each candidate's TMDB
    overview. Returns None if the model can't confidently choose -- the
    caller must fall back to the existing rank/year tiebreak, never treat
    an inconclusive disambiguation as "no match".

    Reliability improvement over a single LLM call: asks the identical
    prompt `_DISAMBIGUATION_SAMPLE_COUNT` (3) separate times via
    `_disambiguate_once`, then requires at least
    `_DISAMBIGUATION_MAJORITY_THRESHOLD` (2) of those samples to agree on
    the same candidate id before trusting it -- see both constants'
    docstrings for why, and the real cost tradeoff (3x the chat-client
    calls for this one tie-break scenario, which only fires when 2+
    exact-title TMDB matches exist for a candidate -- a comparatively rare
    case, not every resolution). No majority (e.g. 3 different ids, or a
    mix of ids/"unknown" with no 2+ agreement) is treated exactly like a
    single honest "unknown": reported as `None`, falling through to the
    existing `pick_best()` rank-tiebreak fallback, unchanged.

    Never raises: every failure mode `_disambiguate_once` can hit (a
    chat-client failure, or any malformed/unparseable reply) is already
    absorbed per-sample; a disambiguation attempt failing is never worse
    than not having attempted it (the caller's fallback is always safe).

    The `_DISAMBIGUATION_SAMPLE_COUNT` samples are independent, data-
    independent blocking chat-client round-trips -- none depends on
    another's result -- so they're run CONCURRENTLY via a small
    `ThreadPoolExecutor`, not one after another. Sequential would triple
    this function's wall-clock latency (e.g. ~2-5s becomes ~6-15s) for no
    reason; concurrent keeps it close to a single sample's latency. Order
    doesn't matter for the majority vote below, so results are collected
    in whatever order the futures finish in.
    """
    with ThreadPoolExecutor(max_workers=_DISAMBIGUATION_SAMPLE_COUNT) as executor:
        votes = list(
            executor.map(
                lambda _: _disambiguate_once(candidates, context, chat_client),
                range(_DISAMBIGUATION_SAMPLE_COUNT),
            )
        )

    vote_counts = Counter(vote for vote in votes if vote is not None)

    majority_id = next(
        (
            candidate_id
            for candidate_id, count in vote_counts.items()
            if count >= _DISAMBIGUATION_MAJORITY_THRESHOLD
        ),
        None,
    )
    if majority_id is None:
        logger.info(
            "disambiguation samples %r had no %d-of-%d majority; treating "
            "as inconclusive",
            votes,
            _DISAMBIGUATION_MAJORITY_THRESHOLD,
            _DISAMBIGUATION_SAMPLE_COUNT,
        )
        return None

    return _find_by_id(candidates, majority_id)


def _extract_year_hint(raw_text: str) -> int | None:
    """Pull an obvious "(YYYY)" year out of candidate text, if present.

    A simple regex, not real date parsing — just enough to pass a year
    hint through to TMDB search / scoring when it's clearly spelled out.

    Uses the LAST "(YYYY)"-shaped match, not the first: `raw_text` is
    always built (by `text_extraction/regex_extractor.py`) as
    `f"{title} ({year})"`, with the real release year appended at the very
    end. If the title itself happens to contain its own parenthesized
    4-digit substring (e.g. a quoted title like "Experience Paris (1920)
    like never before" followed by the real trailing "(2023)"), searching
    from the left would wrongly pick up the title's own embedded year
    instead of the real one. Searching from the right is unambiguous.
    """
    matches = _YEAR_IN_PARENS.findall(raw_text)
    return int(matches[-1]) if matches else None


def _strip_trailing_year(raw_text: str) -> str:
    """Remove a trailing "(YYYY)" from raw_text for use as the TMDB search
    query / fuzzy-match comparand.

    Confirmed against the live TMDB API: searching with a literal "(YYYY)"
    baked into the query can return ZERO results even when the bare title
    matches perfectly (e.g. "Dhobi Ghat (2010)" -> no results; "Dhobi Ghat"
    -> exact match). Only strips a year-in-parens anchored at the very end
    of the string (matching exactly how regex_extractor.py / the claude-CLI
    extractor build raw_text as f"{title} ({year})"), so a title containing
    its OWN embedded parenthetical year earlier in the string (not at the
    end) is left untouched -- same "trailing only" philosophy as
    _extract_year_hint()'s "search from the right" reasoning.

    Loops the substitution: a raw_text ending in TWO adjacent "(YYYY)"
    groups (e.g. a quoted title whose own text happens to end in a year,
    like 'Se7en (1995) (2015)' from a caption such as `Rewatching "Se7en
    (1995)" (2015) tonight`) would otherwise only have its outermost
    trailing year stripped, leaving a still trailing-year-shaped query
    ("Se7en (1995)") that reproduces the exact zero-result dilution bug
    this helper exists to fix. No-ops safely on a string with no trailing
    year match (first iteration's substitution changes nothing).

    Falls back to the original, unstripped `raw_text` if the loop would
    otherwise strip the string down to nothing. This is reachable, not
    just defensive: a candidate whose entire `raw_text` is made of
    chained "(YYYY)"-shaped groups with no other content (e.g. a quoted
    title that is itself just a year, like the real
    `RegexCandidateExtractor` output `'(1999) (2010)'` from a caption
    such as `Watch "(1999)" (2010) now`) loops all the way down to `""`.
    An empty TMDB search query is worse than the original dilution bug:
    it sends no title text at all, instead of merely a diluted one, so a
    non-empty (if imperfect) fallback query is strictly preferable to a
    blank one.
    """
    stripped = raw_text
    while True:
        new = _TRAILING_YEAR_IN_PARENS.sub("", stripped).strip()
        if new == stripped:
            break
        stripped = new
    return stripped or raw_text


def resolve_candidate(
    candidate: Candidate,
    client: TMDBClient,
    context: str | None = None,
    chat_client: TextChatClient | None = None,
    media_type_hint: str | None = None,
) -> ResolvedMovie | None:
    """Resolve a single candidate against TMDB, or None if nothing resolves.

    Signals "nothing resolved" only — per flow.md, it's the caller's (a
    later pipeline subtask's) job to decide whether to keep the candidate
    with `tmdb=None` rather than dropping it.

    `context` (e.g. the reel's caption) and `chat_client` are both
    optional and default to `None` -- a strictly additive, backward-
    compatible enhancement. When 2+ of TMDB's results are a true exact
    title match for the query AND both `context` and `chat_client` are
    given, `disambiguate_with_context()` is asked to pick among that tied
    group using the surrounding text vs. each candidate's overview. If it
    confidently picks one, that pick is used directly, skipping the
    normal `pick_best()` call entirely for this candidate. If it's
    inconclusive (returns `None`), or there are 0-1 exact matches, or
    either `context`/`chat_client` is missing, behavior falls through to
    exactly the pre-existing `pick_best()` call -- never worse than
    before this feature existed.

    `media_type_hint` ("movie" | "tv" | None, from
    `text_extraction/candidate_disambiguation.py`'s noise-filtering pass)
    is another strictly additive, backward-compatible optional filter:
    when not `None`, `client.search()`'s raw results are filtered down to
    just that `media_type` BEFORE `find_exact_matches()`/`pick_best()` (or
    disambiguation) ever see them. Fail-safe: if filtering would eliminate
    EVERY result, the unfiltered list is used instead -- an overzealous or
    wrong hint must never turn a real set of candidates into zero, it can
    only help narrow a genuinely mixed one.
    """
    year_hint = _extract_year_hint(candidate.raw_text)
    query_title = _strip_trailing_year(candidate.raw_text)
    results = client.search(query_title, year=year_hint)

    if media_type_hint is not None:
        hinted_results = [r for r in results if r.media_type == media_type_hint]
        if hinted_results:
            results = hinted_results

    best: TMDBSearchResult | None = None
    exact_matches = find_exact_matches(query_title, results)
    if len(exact_matches) >= 2 and context is not None and chat_client is not None:
        best = disambiguate_with_context(exact_matches, context, chat_client)

    if best is None:
        best = pick_best(query_title, year_hint, results)
    if best is None:
        return None

    return ResolvedMovie(
        id=best.id,
        title=best.title,
        year=best.year,
        poster_path=best.poster_path,
        overview=best.overview,
        match_score=score_result(query_title, year_hint, best),
        media_type=best.media_type,
    )


def resolve_candidate_with_retry(
    candidate: Candidate,
    client: TMDBClient,
    *,
    context: str | None = None,
    chat_client: TextChatClient | None = None,
    media_type_hint: str | None = None,
    deadline_seconds: float = 300.0,
) -> ResolvedMovie | None:
    """Wrap `resolve_candidate()` in a capped-exponential-backoff retry loop.

    `media_type_hint` is forwarded to `resolve_candidate()` unchanged on
    every attempt -- see that function's docstring for what it does.

    Retries the WHOLE `resolve_candidate()` call (search + scoring +
    disambiguation) from scratch on `_RETRYABLE_EXCEPTIONS` --
    `requests.exceptions.ConnectionError`/`Timeout` (which can still reach
    here even after `tmdb/client.py`'s own internal 3-attempt retry is
    exhausted) and `requests.exceptions.HTTPError`, but only when
    `_is_retryable_http_error()` says the specific status code is
    actually plausibly transient (429 or 5xx) -- a real, permanent
    response (401 invalid/expired token, 400, 403, 404, ...) propagates
    immediately instead of being retried for the full `deadline_seconds`
    on something that will never succeed (an expired TMDB token, for
    example, is a config error that should fail fast, not hang this
    function for minutes per candidate). `client.search()` deliberately
    never retries an `HTTPError` itself (a real API-level error response
    isn't a transient connection issue at that layer) -- this outer loop
    is what covers the subset of that case worth covering.
    `tmdb/client.py`'s existing retry logic is untouched; this is a
    second, outer, coarser retry layer on top of it.

    Backoff starts at `_RETRY_INITIAL_BACKOFF_SECONDS` (1s), doubles each
    attempt, capped at `_RETRY_MAX_BACKOFF_SECONDS` (30s) -- not
    configurable beyond `deadline_seconds`, this doesn't need to be clever.

    Always attempts at least once, regardless of `deadline_seconds`.
    After each failed attempt, if the elapsed wall-clock time since this
    call started has already reached `deadline_seconds`, gives up and
    returns `None` -- mapped to `tmdb=None` by the caller exactly like
    today's existing unresolved-candidate handling (not a new error
    state, just a new way of reaching the existing one). Any exception NOT
    in `_RETRYABLE_EXCEPTIONS` (e.g. a genuine bug) propagates immediately,
    unretried.
    """
    start = time.monotonic()
    backoff_seconds = _RETRY_INITIAL_BACKOFF_SECONDS
    while True:
        try:
            return resolve_candidate(
                candidate,
                client,
                context=context,
                chat_client=chat_client,
                media_type_hint=media_type_hint,
            )
        except _RETRYABLE_EXCEPTIONS as exc:
            if isinstance(exc, requests.exceptions.HTTPError) and not _is_retryable_http_error(exc):
                raise
            elapsed = time.monotonic() - start
            if elapsed >= deadline_seconds:
                logger.warning(
                    "giving up resolving %r against TMDB after %.1fs "
                    "(deadline %.1fs exceeded): %s",
                    candidate.raw_text,
                    elapsed,
                    deadline_seconds,
                    exc,
                )
                return None
            sleep_seconds = min(backoff_seconds, deadline_seconds - elapsed)
            logger.info(
                "retrying TMDB resolution for %r after %s (elapsed %.1fs/"
                "%.1fs); sleeping %.1fs",
                candidate.raw_text,
                exc,
                elapsed,
                deadline_seconds,
                sleep_seconds,
            )
            time.sleep(sleep_seconds)
            backoff_seconds = min(
                backoff_seconds * 2, _RETRY_MAX_BACKOFF_SECONDS
            )
