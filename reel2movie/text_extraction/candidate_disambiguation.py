"""Filters noise out of a *pool of extracted candidate strings* (Problem A
in this feature's task brief -- see PROGRESS.md for the full writeup).

This is explicitly NOT the same problem `tmdb/resolver.py`'s
`disambiguate_with_context()` solves (Problem B, the "Don't Be Shy" case):
that function picks among several TMDB ENTRIES that all share one exact
queried TITLE. This module instead picks among several DIFFERENT raw
candidate title STRINGS that `text_extraction/`'s extractors pulled out of
one piece of source text -- some of which may be noise (an unrelated
quoted tagline, a line of dialogue, a hashtag fragment, an incidental/
comparison mention) rather than genuine recommendations -- before any of
them ever reaches TMDB at all.

The key design choice: candidates are classified PER-CANDIDATE
(keep/drop), not "pick one winner". The same mechanism that lets a
"ranked list reel recommending 5 real movies" caption (see brainstorm.md's
"Known hard cases") keep all 5 of its genuine candidates is what lets a
caption with 1 real recommendation buried in noise correctly collapse down
to just that 1 -- there is no separate "single vs multi" branch to keep in
sync.
"""

from __future__ import annotations

import json
import logging
from dataclasses import replace

from reel2movie.core.models import Candidate
from reel2movie.text_extraction.claude_code_extractor import TextChatClient

logger = logging.getLogger(__name__)

_VALID_MEDIA_TYPE_HINTS = frozenset({"movie", "tv"})

_SELECT_PRIMARY_PROMPT_TEMPLATE = """You are reading a piece of text (e.g. an Instagram reel caption, comment, \
or audio transcript) alongside a list of movie/TV-show title strings that \
were mechanically extracted from it. Some of these extracted strings are \
genuine recommendations/discussions the text is actually about; others may \
be noise the extractor happened to pick up -- an unrelated quoted tagline, \
a line of dialogue, a hashtag fragment, or an incidental/comparison \
mention that isn't actually one of the things being recommended.

Source text:
\"\"\"
{source_text}
\"\"\"

Extracted candidate strings (0-indexed):
{candidates}

For EACH candidate, decide: is the source text genuinely recommending or \
discussing this title as one of its subject(s) (keep=true), or is it \
noise relative to what the source text is actually recommending \
(keep=false)? A caption recommending several real movies (e.g. a ranked \
"5 movies like X" list) should have ALL of its real recommendations kept \
-- do not drop a genuine candidate just because there are several of \
them. Only drop a candidate that is genuinely NOT one of the things being \
recommended/discussed.

Also decide one overall media type hint for what the source text as a \
whole is recommending: "movie", "tv", or null if unclear or mixed.

Respond with ONLY a JSON object, and nothing else -- no prose, no markdown \
code fences. Shape:
{{"media_type_hint": "movie" | "tv" | null, "decisions": [{{"index": 0, "keep": true}}, {{"index": 1, "keep": false}}]}}

Include exactly one decision object per candidate index, 0 through {max_index}, \
with "index" matching that candidate's position above.
"""


def _parse_reply(
    raw_reply: str, expected_count: int
) -> tuple[dict[int, bool] | None, str | None]:
    """Parse `raw_reply` into `(decisions, media_type_hint)`.

    `decisions` is `None` if `raw_reply` isn't the exact expected shape
    (valid JSON object, a "decisions" list with exactly one well-formed,
    uniquely-indexed entry per candidate index `0..expected_count-1`) --
    the caller treats that identically to a chat-client exception: keep
    every candidate unchanged. `media_type_hint` is coerced to `None`
    unless it's exactly `"movie"` or `"tv"`.
    """
    try:
        parsed = json.loads(raw_reply.strip())
    except (json.JSONDecodeError, AttributeError):
        return None, None

    if not isinstance(parsed, dict):
        return None, None

    media_type_hint = parsed.get("media_type_hint")
    if media_type_hint not in _VALID_MEDIA_TYPE_HINTS:
        media_type_hint = None

    raw_decisions = parsed.get("decisions")
    if not isinstance(raw_decisions, list) or len(raw_decisions) != expected_count:
        return None, None

    decisions: dict[int, bool] = {}
    for item in raw_decisions:
        if not isinstance(item, dict):
            return None, None
        index = item.get("index")
        keep = item.get("keep")
        # bool is a subclass of int -- isinstance(index, int) alone would
        # wrongly accept e.g. {"index": true}, so bool is excluded
        # explicitly first.
        if isinstance(index, bool) or not isinstance(index, int):
            return None, None
        if not isinstance(keep, bool):
            return None, None
        if index in decisions:
            return None, None
        decisions[index] = keep

    if set(decisions.keys()) != set(range(expected_count)):
        return None, None

    return decisions, media_type_hint


def select_primary_candidates(
    candidates: list[Candidate],
    source_text: str,
    chat_client: TextChatClient,
) -> list[Candidate]:
    """Filter noise out of `candidates` (all extracted from `source_text`),
    keeping only the ones genuinely being recommended/discussed, and
    attach a shared `media_type_hint` to every survivor.

    Skips the LLM call entirely when `len(candidates) <= 1` -- mirrors
    `tmdb/resolver.py`'s `disambiguate_with_context()`'s existing "only
    bother when there's genuine ambiguity" precedent -- and returns
    `candidates` unchanged in that case (nothing to disambiguate between).

    Asks the model a PER-CANDIDATE keep/drop classification (not "pick one
    winner") plus one overall `media_type_hint` ("movie"/"tv"/None) for
    `source_text` as a whole, in a SINGLE model call. See the module
    docstring for why per-candidate classification is the one mechanism
    that correctly handles both a multi-movie "ranked list" caption (every
    genuine candidate kept) and a single-real-candidate-buried-in-noise
    caption (collapses to just the real one).

    Fail-safe, matching `disambiguate_with_context()`'s existing
    philosophy: ANY chat-client exception, or a reply that isn't the exact
    expected JSON shape (see `_parse_reply`), returns `candidates`
    UNCHANGED -- this pass failing must never drop every candidate; a
    noise-filtering attempt that didn't work is never worse than not
    having attempted it.

    Candidates that pass the filter (`keep=true`) get `media_type_hint`
    attached (via `dataclasses.replace`, since `Candidate` is frozen);
    dropped candidates are simply excluded from the returned list, in
    their original relative order.
    """
    if len(candidates) <= 1:
        return candidates

    numbered = "\n".join(f"{i}. {c.raw_text!r}" for i, c in enumerate(candidates))
    # `.format()`, not chained `.replace()` calls: `source_text` is
    # untrusted (a reel caption/comment/transcript) and `.replace()`
    # rescans the WHOLE string -- including content already substituted
    # by an earlier `.replace()` call -- so a `source_text` that happens
    # to contain a literal "{candidates}"/"{max_index}" substring would
    # get mangled by the LATER `.replace()` calls matching inside it.
    # `str.format()` substitutes all placeholders in one pass against the
    # ORIGINAL template, so a substituted value is never rescanned --
    # matching `tmdb/resolver.py`'s `_DISAMBIGUATION_PROMPT_TEMPLATE.format(...)`,
    # which doesn't have this bug for the same reason.
    prompt = _SELECT_PRIMARY_PROMPT_TEMPLATE.format(
        source_text=source_text,
        candidates=numbered,
        max_index=len(candidates) - 1,
    )

    try:
        raw_reply = chat_client.chat(prompt)
    except Exception:
        logger.exception(
            "candidate-noise-filtering chat call failed; keeping all %d "
            "candidate(s) unchanged",
            len(candidates),
        )
        return candidates

    decisions, media_type_hint = _parse_reply(raw_reply, len(candidates))
    if decisions is None:
        logger.warning(
            "candidate-noise-filtering reply was not the expected JSON "
            "shape; keeping all %d candidate(s) unchanged: %r",
            len(candidates),
            raw_reply,
        )
        return candidates

    return [
        replace(candidate, media_type_hint=media_type_hint)
        for i, candidate in enumerate(candidates)
        if decisions[i]
    ]
