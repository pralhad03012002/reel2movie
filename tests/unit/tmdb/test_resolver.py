"""Tests for tmdb/resolver.py, using a fake TMDBClient-shaped object."""

from __future__ import annotations

import threading

import pytest
import requests

from reel2movie.core.models import Candidate, SourceTag, TMDBSearchResult
from reel2movie.tmdb.resolver import (
    _DISAMBIGUATION_MAJORITY_THRESHOLD,
    _DISAMBIGUATION_SAMPLE_COUNT,
    disambiguate_with_context,
    resolve_candidate,
    resolve_candidate_with_retry,
)


class FakeChatClient:
    """A minimal fake `TextChatClient`: a single canned reply (repeated for
    every call), a per-call sequence of replies (for majority-vote tests
    that need different answers across `disambiguate_with_context`'s
    `_DISAMBIGUATION_SAMPLE_COUNT` samples), or a raise.

    Records every prompt it was asked so a test can assert disambiguation
    was (or was never) attempted, and how many times.

    `disambiguate_with_context()`'s `_DISAMBIGUATION_SAMPLE_COUNT` samples
    now run concurrently (see `resolver.py`'s Fix 4), so this fake's
    `chat()` can be called from several threads at once -- a `threading.Lock`
    guards the read-then-increment of `self.call_count` (used both to
    index into `self.replies` and as the recorded call count) so each
    concurrent call still deterministically consumes exactly one, distinct
    reply from the configured sequence, matching this fake's pre-existing
    single-threaded contract exactly.
    """

    def __init__(
        self,
        reply: str = "unknown",
        replies: list[str] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.reply = reply
        self.replies = replies
        self.error = error
        self.prompts: list[str] = []
        self.call_count = 0
        self._lock = threading.Lock()

    def chat(self, prompt: str) -> str:
        with self._lock:
            self.prompts.append(prompt)
            if self.error is not None:
                self.call_count += 1
                raise self.error
            if self.replies is not None:
                reply = self.replies[self.call_count]
                self.call_count += 1
                return reply
            self.call_count += 1
            return self.reply


class FakeTMDBClient:
    """A minimal fake satisfying the TMDBClient Protocol structurally."""

    def __init__(self, results: list[TMDBSearchResult]) -> None:
        self._results = results
        self.last_query: str | None = None
        self.last_year: int | None = None

    def search(
        self, query: str, year: int | None = None
    ) -> list[TMDBSearchResult]:
        self.last_query = query
        self.last_year = year
        return self._results


def _candidate(raw_text: str) -> Candidate:
    return Candidate(raw_text=raw_text, source=SourceTag.CAPTION, confidence=0.9)


def _search_result(**overrides) -> TMDBSearchResult:
    defaults = dict(
        id=603,
        title="The Matrix",
        year=1999,
        poster_path="/matrix.jpg",
        overview="A hacker learns the truth.",
        popularity=80.0,
        original_rank=0,
        media_type="movie",
    )
    defaults.update(overrides)
    return TMDBSearchResult(**defaults)


def test_extracts_year_hint_from_candidate_text():
    client = FakeTMDBClient([_search_result()])

    resolve_candidate(_candidate("The Matrix (1999)"), client)

    assert client.last_year == 1999
    # Regression for the TMDB query-dilution bug: the literal "(1999)"
    # must NOT be sent as part of the search query string (confirmed
    # against the live TMDB API that a baked-in "(YYYY)" can return zero
    # results even for an exact title match) -- the year is passed
    # separately via `year=`.
    assert client.last_query == "The Matrix"


def test_no_year_hint_when_no_parenthesized_year_present():
    client = FakeTMDBClient([_search_result()])

    resolve_candidate(_candidate("The Matrix"), client)

    assert client.last_year is None


def test_maps_winning_result_to_resolved_movie():
    client = FakeTMDBClient([_search_result()])

    resolved = resolve_candidate(_candidate("The Matrix (1999)"), client)

    assert resolved is not None
    assert resolved.id == 603
    assert resolved.title == "The Matrix"
    assert resolved.year == 1999
    assert resolved.poster_path == "/matrix.jpg"
    assert resolved.overview == "A hacker learns the truth."
    assert isinstance(resolved.match_score, float)
    assert resolved.media_type == "movie"
    # popularity/original_rank are dropped, not present on ResolvedMovie
    assert not hasattr(resolved, "popularity")
    assert not hasattr(resolved, "original_rank")


def test_maps_tv_result_to_resolved_movie_with_tv_media_type():
    """Regression for the real "The Mentalist" bug: a fake client returning
    a tv-show-shaped `TMDBSearchResult` (media_type="tv") must produce a
    `ResolvedMovie` with `media_type="tv"` correctly populated, not
    silently dropped or defaulted to "movie".
    """
    tv_result = _search_result(
        id=5920,
        title="The Mentalist",
        year=2008,
        poster_path="/mentalist.jpg",
        overview="A former psychic medium solves crimes.",
        media_type="tv",
    )
    client = FakeTMDBClient([tv_result])

    resolved = resolve_candidate(_candidate("The Mentalist"), client)

    assert resolved is not None
    assert resolved.id == 5920
    assert resolved.title == "The Mentalist"
    assert resolved.media_type == "tv"


def test_returns_none_when_nothing_resolves():
    client = FakeTMDBClient([])

    resolved = resolve_candidate(_candidate("Some Obscure Nonexistent Title"), client)

    assert resolved is None


def test_returns_none_when_best_result_is_low_confidence():
    client = FakeTMDBClient(
        [_search_result(title="Completely Unrelated Thing", year=None, original_rank=7)]
    )

    resolved = resolve_candidate(_candidate("The Matrix"), client)

    assert resolved is None


def test_year_hint_uses_last_parenthesized_year_not_first():
    """Regression for Subtask 3 review finding #2: raw_text can contain
    an embedded "(YYYY)"-shaped substring that isn't the real year (e.g.
    a quoted title that itself mentions a year), with the real trailing
    release year appended after it by text_extraction/regex_extractor.py.
    `_extract_year_hint()` must pick the LAST match, not the first."""
    client = FakeTMDBClient([_search_result()])

    raw_text = 'Experience Paris (1920) like never before (2023)'
    resolve_candidate(_candidate(raw_text), client)

    assert client.last_year == 2023


def test_query_strips_only_trailing_year_not_embedded_one():
    """Regression for the TMDB query-dilution bug, combined with the
    embedded-year edge case: only the TRAILING "(2023)" should be
    stripped from the search query, leaving the title's own embedded
    "(1920)" untouched (same "trailing only" anchoring as
    `_extract_year_hint`)."""
    client = FakeTMDBClient([_search_result()])

    raw_text = "Experience Paris (1920) like never before (2023)"
    resolve_candidate(_candidate(raw_text), client)

    assert client.last_query == "Experience Paris (1920) like never before"


def test_query_strips_trailing_year_for_high_confidence_candidate():
    """The exact real-world bug case: a "Title (YYYY)" candidate must be
    searched with just the title -- confirmed against the live TMDB API
    that the literal "(YYYY)" baked into the query can return zero
    results even for an exact title match."""
    client = FakeTMDBClient([_search_result(title="Inception", year=2010)])

    resolve_candidate(_candidate("Inception (2010)"), client)

    assert client.last_query == "Inception"
    assert client.last_year == 2010


def test_query_unchanged_when_no_year_present():
    """A MEDIUM-confidence bare-title candidate (no year in raw_text) has
    nothing to strip -- the query passed to TMDB must be exactly the
    original raw_text, untouched."""
    client = FakeTMDBClient([_search_result(title="Interstellar", year=2014)])

    resolve_candidate(_candidate("Interstellar"), client)

    assert client.last_query == "Interstellar"
    assert client.last_year is None


def test_query_strips_adjacent_double_trailing_year():
    """Regression for the review-blocking adjacent-double-trailing-year
    case: a caption like `Rewatching "Se7en (1995)" (2015) tonight` --
    reachable via RegexCandidateExtractor's quoted-title pattern, which
    has no restriction against parens inside a quoted title -- produces
    raw_text='Se7en (1995) (2015)'. A single-pass strip only removes the
    outer "(2015)", leaving "Se7en (1995)" -- itself still
    trailing-year-shaped, reproducing the exact zero-result TMDB dilution
    bug this whole fix exists to close (confirmed live:
    search_movie("Se7en (1995)", year=2015) -> 0 results;
    search_movie("Se7en", year=2015) -> 7 results). The query sent must be
    fully stripped down to "Se7en"."""
    client = FakeTMDBClient([_search_result(title="Se7en", year=1995)])

    raw_text = "Se7en (1995) (2015)"
    resolve_candidate(_candidate(raw_text), client)

    assert client.last_query == "Se7en"
    assert client.last_year == 2015


def test_query_falls_back_to_raw_text_when_fully_stripped_to_empty():
    """Regression for the cycle-2 review-blocking empty-query case: a
    candidate whose raw_text is made ENTIRELY of chained "(YYYY)"-shaped
    groups, with no other content, strips all the way down to "" via the
    adjacent-year loop above. This is reachable through the real
    RegexCandidateExtractor's quoted-title pattern -- a caption like
    `Watch "(1999)" (2010) now` produces
    Candidate(raw_text='(1999) (2010)', confidence=0.9) because the
    quoted-title capture group has no restriction against the quoted text
    itself looking like a year. Sending an empty query to TMDB is strictly
    worse than the original dilution bug (which at least sent some
    non-empty text), so the fallback must be the full original raw_text,
    not "".
    """
    client = FakeTMDBClient([_search_result()])

    raw_text = "(1999) (2010)"
    resolve_candidate(_candidate(raw_text), client)

    assert client.last_query == raw_text
    assert client.last_query != ""
    assert client.last_year == 2010


def test_query_strips_three_adjacent_trailing_years():
    """Loop-termination stress test (from the cycle-2 review): three
    adjacent "(YYYY)"-shaped trailing groups must still fully reduce to
    the bare title, confirming the empty-query guard didn't regress the
    already-working multi-strip behavior."""
    client = FakeTMDBClient([_search_result(title="Title", year=2020)])

    raw_text = "Title (1111) (2222) (2020)"
    resolve_candidate(_candidate(raw_text), client)

    assert client.last_query == "Title"
    assert client.last_year == 2020


def test_match_score_uses_stripped_query_not_raw_text_with_year():
    """`score_result`/`pick_best` must also receive the stripped query --
    not the original raw_text with the year still baked in -- since the
    fuzzy-match comparand is diluted the same way the search query is.

    Verified by comparing the actual resolved `match_score` against what
    `score_result` would produce for the stripped vs. unstripped query:
    the trailing "(2010)" in the raw, unstripped query measurably lowers
    the fuzzy title-similarity term against a bare TMDB title, so the two
    scores differ, and the resolved score must match the stripped one.
    """
    from reel2movie.tmdb.scoring import score_result

    result = _search_result(title="Inception", year=2010, original_rank=0)
    client = FakeTMDBClient([result])

    resolved = resolve_candidate(_candidate("Inception (2010)"), client)

    assert resolved is not None
    stripped_score = score_result("Inception", 2010, result)
    unstripped_score = score_result("Inception (2010)", 2010, result)
    assert stripped_score != unstripped_score
    assert resolved.match_score == stripped_score


# ---------------------------------------------------------------------------
# disambiguate_with_context() — direct tests
# ---------------------------------------------------------------------------


def _tied_rom_com_and_threesome_results() -> list[TMDBSearchResult]:
    """The real-world "Don't Be Shy" shape: two different movies exactly
    titled "Don't Be Shy", one the real Amazon Prime rom-com, one an
    unrelated adult-themed movie -- TMDB popularity/rank alone can't
    distinguish them."""
    rom_com = _search_result(
        id=111,
        title="Don't Be Shy",
        year=2025,
        overview="A college student navigates chaotic campus life and a "
        "budding romance as she figures out who she really is.",
        original_rank=0,
    )
    unrelated_adult_themed = _search_result(
        id=1586276,
        title="Don't Be Shy",
        year=2025,
        overview="Three friends explore an unconventional relationship "
        "together.",
        original_rank=1,
    )
    return [rom_com, unrelated_adult_themed]


def test_disambiguate_with_context_returns_candidate_the_model_picked_by_id():
    candidates = _tied_rom_com_and_threesome_results()
    chat_client = FakeChatClient(reply="111")

    result = disambiguate_with_context(
        candidates, "A rom-com about college life, from Amazon Prime.", chat_client
    )

    assert result is candidates[0]
    assert result.id == 111


def test_disambiguate_with_context_returns_none_on_unknown_reply():
    candidates = _tied_rom_com_and_threesome_results()
    chat_client = FakeChatClient(reply="unknown")

    result = disambiguate_with_context(candidates, "some ambiguous context", chat_client)

    assert result is None


def test_disambiguate_with_context_returns_none_on_garbage_reply():
    candidates = _tied_rom_com_and_threesome_results()
    chat_client = FakeChatClient(reply="not a number or unknown")

    result = disambiguate_with_context(candidates, "some context", chat_client)

    assert result is None


def test_disambiguate_with_context_returns_none_when_id_not_among_candidates():
    candidates = _tied_rom_com_and_threesome_results()
    chat_client = FakeChatClient(reply="999999999")

    result = disambiguate_with_context(candidates, "some context", chat_client)

    assert result is None


def test_disambiguate_with_context_returns_none_when_chat_client_raises():
    candidates = _tied_rom_com_and_threesome_results()
    chat_client = FakeChatClient(error=RuntimeError("the claude CLI blew up"))

    result = disambiguate_with_context(candidates, "some context", chat_client)

    assert result is None


# ---------------------------------------------------------------------------
# disambiguate_with_context() — majority-vote reliability improvement
# ---------------------------------------------------------------------------


def test_disambiguate_with_context_uses_id_on_unanimous_agreement():
    """3 consistent replies -> that id is used, and the chat client was
    actually asked `_DISAMBIGUATION_SAMPLE_COUNT` times, not just once."""
    candidates = _tied_rom_com_and_threesome_results()
    chat_client = FakeChatClient(replies=["111", "111", "111"])

    result = disambiguate_with_context(candidates, "some context", chat_client)

    assert result is not None
    assert result.id == 111
    assert chat_client.call_count == _DISAMBIGUATION_SAMPLE_COUNT


def test_disambiguate_with_context_uses_id_on_two_of_three_majority():
    """2-of-3 majority (one dissenting sample) -> the majority id is still
    used."""
    candidates = _tied_rom_com_and_threesome_results()
    chat_client = FakeChatClient(replies=["111", "222", "111"])

    result = disambiguate_with_context(candidates, "some context", chat_client)

    assert result is not None
    assert result.id == 111
    assert chat_client.call_count == _DISAMBIGUATION_SAMPLE_COUNT


def test_disambiguate_with_context_inconclusive_when_three_different_replies():
    """No majority (3 different ids) -> treated as inconclusive, falling
    through to `pick_best()` -- confirmed by the chat client having
    actually been called the full configured number of times."""
    candidates = _tied_rom_com_and_threesome_results()
    chat_client = FakeChatClient(replies=["111", "222", "unknown"])

    result = disambiguate_with_context(candidates, "some context", chat_client)

    assert result is None
    assert chat_client.call_count == _DISAMBIGUATION_SAMPLE_COUNT


def test_disambiguate_with_context_inconclusive_when_split_with_no_majority():
    """A mix of a valid id and "unknown" replies, with no single id
    reaching the 2-of-3 majority threshold -> inconclusive."""
    candidates = _tied_rom_com_and_threesome_results()
    chat_client = FakeChatClient(replies=["111", "unknown", "unknown"])

    result = disambiguate_with_context(candidates, "some context", chat_client)

    assert result is None
    assert chat_client.call_count == _DISAMBIGUATION_SAMPLE_COUNT
    # Sanity-check the constant this test's framing relies on.
    assert _DISAMBIGUATION_MAJORITY_THRESHOLD == 2
    assert _DISAMBIGUATION_SAMPLE_COUNT == 3


def test_disambiguate_with_context_prompt_includes_context_and_overviews():
    candidates = _tied_rom_com_and_threesome_results()
    chat_client = FakeChatClient(reply="111")

    disambiguate_with_context(candidates, "THE_UNIQUE_CONTEXT_MARKER", chat_client)

    # The majority-vote reliability improvement samples the identical
    # prompt `_DISAMBIGUATION_SAMPLE_COUNT` times, not once.
    assert len(chat_client.prompts) == _DISAMBIGUATION_SAMPLE_COUNT
    prompt = chat_client.prompts[0]
    assert "THE_UNIQUE_CONTEXT_MARKER" in prompt
    assert "college student navigates chaotic campus life" in prompt
    assert "unconventional relationship" in prompt
    assert "111" in prompt
    assert "1586276" in prompt


# ---------------------------------------------------------------------------
# resolve_candidate() — disambiguation wiring
# ---------------------------------------------------------------------------


def test_resolve_candidate_uses_disambiguation_pick_when_confident():
    """(a) disambiguation picks a specific id -> that exact
    TMDBSearchResult is returned as `best`, confirmed via the resolved
    ResolvedMovie's id."""
    candidates = _tied_rom_com_and_threesome_results()
    client = FakeTMDBClient(candidates)
    chat_client = FakeChatClient(reply="111")

    resolved = resolve_candidate(
        _candidate("Don't Be Shy"),
        client,
        context="A rom-com about college life, from Amazon Prime.",
        chat_client=chat_client,
    )

    assert resolved is not None
    assert resolved.id == 111
    # The majority-vote reliability improvement samples
    # `_DISAMBIGUATION_SAMPLE_COUNT` times for this one tie-break call, not
    # once.
    assert chat_client.call_count == _DISAMBIGUATION_SAMPLE_COUNT


def test_resolve_candidate_falls_back_to_pick_best_when_disambiguation_unknown():
    """(b) disambiguation returns "unknown" -> falls back to the existing
    rank/year pick_best() behavior -- proved by asserting the SAME
    ResolvedMovie comes back whether disambiguation is skipped entirely
    or returns "unknown"."""
    candidates = _tied_rom_com_and_threesome_results()

    client_with_disambiguation = FakeTMDBClient(candidates)
    chat_client = FakeChatClient(reply="unknown")
    resolved_with_unknown = resolve_candidate(
        _candidate("Don't Be Shy"),
        client_with_disambiguation,
        context="some ambiguous caption",
        chat_client=chat_client,
    )

    client_without_disambiguation = FakeTMDBClient(candidates)
    resolved_without_disambiguation = resolve_candidate(
        _candidate("Don't Be Shy"), client_without_disambiguation
    )

    assert chat_client.call_count == _DISAMBIGUATION_SAMPLE_COUNT
    assert resolved_with_unknown is not None
    assert resolved_without_disambiguation is not None
    assert resolved_with_unknown == resolved_without_disambiguation


def test_resolve_candidate_without_context_or_chat_client_is_unchanged():
    """(c) context/chat_client not provided at all (both None, the
    default) -> behavior is byte-for-byte identical to the pre-this-fix
    resolve_candidate -- same two-exact-match setup, called with no new
    arguments at all."""
    candidates = _tied_rom_com_and_threesome_results()
    client = FakeTMDBClient(candidates)

    resolved = resolve_candidate(_candidate("Don't Be Shy"), client)

    assert resolved is not None
    # pick_best()'s own tiebreak (rank_bonus) wins: original_rank=0 beats
    # original_rank=1 among the exact-match tier, with no disambiguation
    # involved at all.
    assert resolved.id == 111


def test_resolve_candidate_never_attempts_disambiguation_with_only_one_exact_match():
    """(d) only 1 exact match exists -> disambiguation is never even
    attempted (the fake chat client's call count is 0), since there is
    nothing to disambiguate."""
    client = FakeTMDBClient([_search_result(id=603, title="The Matrix")])
    chat_client = FakeChatClient(reply="603")

    resolved = resolve_candidate(
        _candidate("The Matrix"),
        client,
        context="some context",
        chat_client=chat_client,
    )

    assert resolved is not None
    assert resolved.id == 603
    assert chat_client.call_count == 0


def test_resolve_candidate_disambiguation_not_attempted_with_only_context_no_chat_client():
    """Only one of `context`/`chat_client` provided -> disambiguation must
    not run at all (both are required)."""
    candidates = _tied_rom_com_and_threesome_results()
    client = FakeTMDBClient(candidates)

    resolved = resolve_candidate(
        _candidate("Don't Be Shy"), client, context="some caption text"
    )

    assert resolved is not None
    assert resolved.id == 111  # pick_best()'s rank tiebreak, unchanged


def test_resolve_candidate_disambiguation_not_attempted_with_only_chat_client_no_context():
    """Only `chat_client` provided, no `context` -> disambiguation must not
    run at all (both are required)."""
    candidates = _tied_rom_com_and_threesome_results()
    client = FakeTMDBClient(candidates)
    chat_client = FakeChatClient(reply="111")

    resolved = resolve_candidate(
        _candidate("Don't Be Shy"), client, chat_client=chat_client
    )

    assert resolved is not None
    assert resolved.id == 111  # pick_best()'s rank tiebreak, unchanged
    assert chat_client.call_count == 0


# ---------------------------------------------------------------------------
# resolve_candidate_with_retry()
# ---------------------------------------------------------------------------


class FlakyThenSucceedsTMDBClient:
    """A fake `TMDBClient` whose `search()` raises a given exception for
    the first `fail_times` calls, then succeeds -- used to prove
    `resolve_candidate_with_retry` retries the WHOLE `resolve_candidate()`
    call from scratch, not just the low-level HTTP request.
    """

    def __init__(
        self, exception: Exception, fail_times: int, results: list[TMDBSearchResult]
    ) -> None:
        self._exception = exception
        self._fail_times = fail_times
        self._results = results
        self.call_count = 0

    def search(self, query: str, year: int | None = None) -> list[TMDBSearchResult]:
        self.call_count += 1
        if self.call_count <= self._fail_times:
            raise self._exception
        return self._results


def _http_error(status_code: int, message: str = "error") -> requests.exceptions.HTTPError:
    """Build a `requests.exceptions.HTTPError` with a real `.response`
    carrying `status_code` -- matching how `requests` actually raises one
    (via `response.raise_for_status()`, which always attaches the
    response), not a bare message-only exception, since
    `resolve_candidate_with_retry`'s retry-worthiness check
    (`_is_retryable_http_error`) inspects `exc.response.status_code`.
    """
    response = requests.Response()
    response.status_code = status_code
    return requests.exceptions.HTTPError(message, response=response)


class AlwaysFailingTMDBClient:
    """A fake `TMDBClient` whose `search()` always raises -- used to prove
    `resolve_candidate_with_retry` gives up once `deadline_seconds` has
    elapsed, rather than retrying forever."""

    def __init__(self, exception: Exception) -> None:
        self._exception = exception
        self.call_count = 0

    def search(self, query: str, year: int | None = None) -> list[TMDBSearchResult]:
        self.call_count += 1
        raise self._exception


def test_resolve_candidate_with_retry_succeeds_after_a_connection_error():
    client = FlakyThenSucceedsTMDBClient(
        requests.exceptions.ConnectionError("TLS handshake reset"),
        fail_times=1,
        results=[_search_result()],
    )

    resolved = resolve_candidate_with_retry(
        _candidate("The Matrix (1999)"), client, deadline_seconds=10.0
    )

    assert resolved is not None
    assert resolved.id == 603
    assert client.call_count == 2


def test_resolve_candidate_with_retry_succeeds_after_an_http_error():
    """Per the task spec: `tmdb/client.py`'s own internal retry never
    retries `requests.exceptions.HTTPError` (a real 4xx/5xx response) --
    this OUTER retry loop is specifically what covers that case, for a
    plausibly-transient status code (503)."""
    client = FlakyThenSucceedsTMDBClient(
        _http_error(503, "503 Service Unavailable"),
        fail_times=1,
        results=[_search_result()],
    )

    resolved = resolve_candidate_with_retry(
        _candidate("The Matrix (1999)"), client, deadline_seconds=10.0
    )

    assert resolved is not None
    assert resolved.id == 603
    assert client.call_count == 2


def test_resolve_candidate_with_retry_succeeds_after_a_429():
    """429 (rate limited) is the other explicitly-retryable HTTP status,
    alongside the 5xx range covered by the test above."""
    client = FlakyThenSucceedsTMDBClient(
        _http_error(429, "429 Too Many Requests"),
        fail_times=1,
        results=[_search_result()],
    )

    resolved = resolve_candidate_with_retry(
        _candidate("The Matrix (1999)"), client, deadline_seconds=10.0
    )

    assert resolved is not None
    assert resolved.id == 603
    assert client.call_count == 2


def test_resolve_candidate_with_retry_does_not_retry_a_permanent_http_error():
    """Regression test: a 401 (e.g. an invalid/expired TMDB token) is a
    permanent, non-transient failure that will never succeed no matter how
    many times it's retried. Unlike a 429/5xx, this must propagate
    immediately -- NOT get retried for the full `deadline_seconds` (5
    minutes by default), which would turn a config error into a
    multi-minute hang per candidate instead of an immediate, diagnosable
    failure.
    """
    client = AlwaysFailingTMDBClient(_http_error(401, "401 Unauthorized"))

    with pytest.raises(requests.exceptions.HTTPError):
        resolve_candidate_with_retry(
            _candidate("The Matrix (1999)"), client, deadline_seconds=10.0
        )

    # Exactly one attempt -- no retry at all for a permanent error.
    assert client.call_count == 1


def test_resolve_candidate_with_retry_gives_up_after_deadline_and_returns_none():
    """Uses a short `deadline_seconds` (not a real 300s/5-minute wait) so
    this test stays fast: the client always fails, so
    `resolve_candidate_with_retry` must retry at least once, then give up
    once the deadline is exceeded -- returning `None` (never raising),
    mapped by the caller to the existing `tmdb=None` unresolved state.
    """
    client = AlwaysFailingTMDBClient(
        requests.exceptions.ConnectionError("TLS handshake reset")
    )

    resolved = resolve_candidate_with_retry(
        _candidate("The Matrix (1999)"), client, deadline_seconds=0.05
    )

    assert resolved is None
    assert client.call_count >= 2


def test_resolve_candidate_with_retry_tries_at_least_once_even_with_zero_deadline():
    client = AlwaysFailingTMDBClient(requests.exceptions.Timeout("timed out"))

    resolved = resolve_candidate_with_retry(
        _candidate("The Matrix (1999)"), client, deadline_seconds=0.0
    )

    assert resolved is None
    assert client.call_count == 1


def test_resolve_candidate_with_retry_propagates_non_retryable_exceptions():
    """A genuine bug (anything not in `_RETRYABLE_EXCEPTIONS`) must
    propagate immediately, unretried -- `resolve_candidate_with_retry`
    only absorbs connection/timeout/HTTP errors, never every exception."""

    class ExplodingTMDBClient:
        def search(self, query: str, year: int | None = None):
            raise TypeError("a genuine bug, not a transient TMDB failure")

    with pytest.raises(TypeError, match="a genuine bug"):
        resolve_candidate_with_retry(
            _candidate("The Matrix (1999)"), ExplodingTMDBClient(), deadline_seconds=5.0
        )


def test_resolve_candidate_with_retry_passes_context_and_chat_client_through():
    """Confirms `resolve_candidate_with_retry` is a thin wrapper that still
    threads `context`/`chat_client` through to `resolve_candidate` for
    disambiguation, same as calling `resolve_candidate` directly."""
    candidates = _tied_rom_com_and_threesome_results()
    client = FakeTMDBClient(candidates)
    chat_client = FakeChatClient(reply="111")

    resolved = resolve_candidate_with_retry(
        _candidate("Don't Be Shy"),
        client,
        context="A rom-com about college life, from Amazon Prime.",
        chat_client=chat_client,
        deadline_seconds=10.0,
    )

    assert resolved is not None
    assert resolved.id == 111
    assert chat_client.call_count == _DISAMBIGUATION_SAMPLE_COUNT


# ---------------------------------------------------------------------------
# resolve_candidate() — media_type_hint filtering
# ---------------------------------------------------------------------------


def test_resolve_candidate_media_type_hint_filters_results():
    """A `media_type_hint` that matches SOME of the search results filters
    the pool down to just those before scoring -- proved by picking a
    scenario where the unfiltered pool's winner would differ from the
    filtered pool's winner."""
    movie_result = _search_result(
        id=1, title="The Mentalist", media_type="movie", original_rank=0
    )
    tv_result = _search_result(
        id=2, title="The Mentalist", media_type="tv", original_rank=1
    )
    client = FakeTMDBClient([movie_result, tv_result])

    resolved = resolve_candidate(
        _candidate("The Mentalist"), client, media_type_hint="tv"
    )

    assert resolved is not None
    assert resolved.id == 2
    assert resolved.media_type == "tv"


def test_resolve_candidate_media_type_hint_matching_none_falls_back_to_unfiltered():
    """A `media_type_hint` that matches NONE of the search results must
    fall back to the unfiltered list -- never let an overzealous/wrong
    hint turn a real set of results into zero."""
    movie_result = _search_result(id=1, title="The Mentalist", media_type="movie")
    client = FakeTMDBClient([movie_result])

    resolved = resolve_candidate(
        _candidate("The Mentalist"), client, media_type_hint="tv"
    )

    assert resolved is not None
    assert resolved.id == 1
    assert resolved.media_type == "movie"


def test_resolve_candidate_without_media_type_hint_is_unchanged():
    """`media_type_hint` defaults to `None` -- behavior is identical to
    before this feature for a call that doesn't pass it at all."""
    movie_result = _search_result(
        id=1, title="The Mentalist", media_type="movie", original_rank=0
    )
    tv_result = _search_result(
        id=2, title="The Mentalist", media_type="tv", original_rank=1
    )
    client = FakeTMDBClient([movie_result, tv_result])

    resolved = resolve_candidate(_candidate("The Mentalist"), client)

    assert resolved is not None
    # pick_best()'s rank tiebreak (original_rank=0) wins, with no
    # media-type filtering involved at all.
    assert resolved.id == 1
