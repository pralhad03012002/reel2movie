"""Tests for `text_extraction/candidate_disambiguation.py`'s
`select_primary_candidates()` -- Problem A's noise filter: picking which
extracted candidate STRINGS are genuine recommendations vs. noise, out of
a pool all pulled from the SAME source text.
"""

from __future__ import annotations

import json

from reel2movie.core.models import Candidate, SourceTag
from reel2movie.text_extraction.candidate_disambiguation import (
    select_primary_candidates,
)


class FakeChatClient:
    """A minimal fake `TextChatClient`: configurable canned reply, or a
    raise. Records every prompt it was asked."""

    def __init__(self, reply: str = "", error: Exception | None = None) -> None:
        self.reply = reply
        self.error = error
        self.prompts: list[str] = []
        self.call_count = 0

    def chat(self, prompt: str) -> str:
        self.call_count += 1
        self.prompts.append(prompt)
        if self.error is not None:
            raise self.error
        return self.reply


def _candidate(raw_text: str, source: SourceTag = SourceTag.CAPTION) -> Candidate:
    return Candidate(raw_text=raw_text, source=source, confidence=0.9)


def _keep_all_reply(count: int, media_type_hint: str | None = None) -> str:
    return json.dumps(
        {
            "media_type_hint": media_type_hint,
            "decisions": [{"index": i, "keep": True} for i in range(count)],
        }
    )


def test_skips_llm_call_with_zero_candidates():
    chat_client = FakeChatClient(reply="should never be read")

    result = select_primary_candidates([], "some source text", chat_client)

    assert result == []
    assert chat_client.call_count == 0


def test_skips_llm_call_with_one_candidate():
    candidates = [_candidate("The Matrix")]
    chat_client = FakeChatClient(reply="should never be read")

    result = select_primary_candidates(candidates, "some source text", chat_client)

    assert result == candidates
    assert chat_client.call_count == 0


def test_ranked_list_reel_keeps_all_five_genuine_candidates():
    """The brainstorm.md "ranked list reel recommending 5 real movies" case
    must keep every genuine candidate -- the per-candidate keep/drop
    mechanism must not collapse a legitimately multi-recommendation
    caption down to fewer than all 5.
    """
    candidates = [
        _candidate("Movie One"),
        _candidate("Movie Two"),
        _candidate("Movie Three"),
        _candidate("Movie Four"),
        _candidate("Movie Five"),
    ]
    chat_client = FakeChatClient(reply=_keep_all_reply(5, media_type_hint="movie"))

    result = select_primary_candidates(
        candidates, "5 movies like Inception, ranked", chat_client
    )

    assert [c.raw_text for c in result] == [c.raw_text for c in candidates]
    assert all(c.media_type_hint == "movie" for c in result)
    assert chat_client.call_count == 1


def test_single_real_candidate_buried_in_noise_drops_the_noise():
    """One genuine recommendation plus several noise candidates (a
    tagline, a hashtag fragment, a comparison mention) must collapse down
    to just the real one.
    """
    candidates = [
        _candidate("Some Random Quoted Tagline"),
        _candidate("Dhobi Ghat"),
        _candidate("UnrelatedHashtagPhrase"),
    ]
    reply = json.dumps(
        {
            "media_type_hint": "movie",
            "decisions": [
                {"index": 0, "keep": False},
                {"index": 1, "keep": True},
                {"index": 2, "keep": False},
            ],
        }
    )
    chat_client = FakeChatClient(reply=reply)

    result = select_primary_candidates(
        candidates,
        "Dhobi Ghat is a 2010 Indian drama film you have to watch.",
        chat_client,
    )

    assert len(result) == 1
    assert result[0].raw_text == "Dhobi Ghat"
    assert result[0].media_type_hint == "movie"


def test_chat_client_exception_returns_candidates_unchanged():
    candidates = [_candidate("Movie A"), _candidate("Movie B")]
    chat_client = FakeChatClient(error=RuntimeError("the claude CLI blew up"))

    result = select_primary_candidates(candidates, "some source text", chat_client)

    assert result == candidates


def test_garbage_reply_returns_candidates_unchanged():
    candidates = [_candidate("Movie A"), _candidate("Movie B")]
    chat_client = FakeChatClient(reply="not json at all, just prose")

    result = select_primary_candidates(candidates, "some source text", chat_client)

    assert result == candidates


def test_reply_missing_a_decision_returns_candidates_unchanged():
    """A reply that's valid JSON but doesn't have exactly one decision per
    candidate index is treated the same as garbage -- never partially
    trusted."""
    candidates = [_candidate("Movie A"), _candidate("Movie B")]
    reply = json.dumps(
        {"media_type_hint": None, "decisions": [{"index": 0, "keep": True}]}
    )
    chat_client = FakeChatClient(reply=reply)

    result = select_primary_candidates(candidates, "some source text", chat_client)

    assert result == candidates


def test_media_type_hint_attached_on_success():
    candidates = [_candidate("Show A"), _candidate("Show B")]
    chat_client = FakeChatClient(reply=_keep_all_reply(2, media_type_hint="tv"))

    result = select_primary_candidates(candidates, "some source text", chat_client)

    assert len(result) == 2
    assert all(c.media_type_hint == "tv" for c in result)


def test_invalid_media_type_hint_coerced_to_none():
    """A `media_type_hint` value that isn't exactly "movie" or "tv" (e.g. a
    model hallucinating something else) is coerced to `None`, never passed
    through verbatim."""
    candidates = [_candidate("Movie A"), _candidate("Movie B")]
    reply = json.dumps(
        {
            "media_type_hint": "documentary",
            "decisions": [
                {"index": 0, "keep": True},
                {"index": 1, "keep": True},
            ],
        }
    )
    chat_client = FakeChatClient(reply=reply)

    result = select_primary_candidates(candidates, "some source text", chat_client)

    assert all(c.media_type_hint is None for c in result)


def test_prompt_includes_source_text_and_candidate_strings():
    candidates = [_candidate("Movie A"), _candidate("Movie B")]
    chat_client = FakeChatClient(reply=_keep_all_reply(2))

    select_primary_candidates(candidates, "THE_UNIQUE_SOURCE_TEXT_MARKER", chat_client)

    assert len(chat_client.prompts) == 1
    prompt = chat_client.prompts[0]
    assert "THE_UNIQUE_SOURCE_TEXT_MARKER" in prompt
    assert "Movie A" in prompt
    assert "Movie B" in prompt


def test_source_text_containing_literal_placeholder_substrings_passes_through_unmangled():
    """Regression test: the prompt used to be built via chained `.replace()`
    calls, where each `.replace()` rescans the WHOLE string including
    already-substituted content. If `source_text` (untrusted caption/
    comment/transcript text) happened to contain a literal "{candidates}"
    or "{max_index}" substring, a LATER `.replace()` call would corrupt the
    just-inserted source_text by matching inside it. Using `str.format()`
    (substituting all placeholders in one pass against the original
    template) fixes this -- confirm the literal substrings survive intact
    in the final prompt, and the real candidate/source text aren't
    corrupted.
    """
    candidates = [_candidate("Movie A"), _candidate("Movie B")]
    chat_client = FakeChatClient(reply=_keep_all_reply(2))
    source_text = "check this out {candidates} and also {max_index} for more info"

    select_primary_candidates(candidates, source_text, chat_client)

    assert len(chat_client.prompts) == 1
    prompt = chat_client.prompts[0]
    assert source_text in prompt
    assert "0. 'Movie A'" in prompt
    assert "1. 'Movie B'" in prompt
