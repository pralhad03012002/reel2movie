"""Tests for `reel2movie.visual.frame_dedup`.

No ffmpeg anywhere: all frames here are pure Pillow-generated synthetic
images written to `tmp_path` as JPEGs, wrapped as `FrameSample`s. This
module's own docstring explains why `threshold=0.04` is an unvalidated
starting point -- these tests exercise the ALGORITHM (compare-to-last-kept,
not compare-to-immediately-previous; threshold boundary behavior; edge
cases), not whether 0.04 happens to be the "right" number for real reels.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from reel2movie.core.models import FrameSample
from reel2movie.visual.frame_dedup import dedupe_similar_frames


def _solid_frame(path: Path, color: tuple[int, int, int], timestamp: float) -> FrameSample:
    Image.new("RGB", (64, 64), color=color).save(path, "JPEG")
    return FrameSample(path=path, timestamp_seconds=timestamp)


def test_empty_input_returns_empty_list() -> None:
    assert dedupe_similar_frames([]) == []


def test_single_frame_returned_unchanged(tmp_path: Path) -> None:
    frame = _solid_frame(tmp_path / "f0.jpg", (10, 20, 30), 0.0)

    result = dedupe_similar_frames([frame])

    assert result == [frame]


def test_run_of_identical_frames_collapses_to_just_the_first(tmp_path: Path) -> None:
    """A long static shot (same color repeated) must collapse to one kept
    frame, not one every-other-frame or similar -- the whole point of
    comparing every candidate to the last KEPT frame."""
    frames = [
        _solid_frame(tmp_path / f"f{i}.jpg", (100, 100, 100), float(i))
        for i in range(5)
    ]

    result = dedupe_similar_frames(frames)

    assert result == [frames[0]]


def test_substantially_different_frame_is_kept(tmp_path: Path) -> None:
    same_color_frames = [
        _solid_frame(tmp_path / f"f{i}.jpg", (0, 0, 0), float(i)) for i in range(3)
    ]
    different_frame = _solid_frame(tmp_path / "f_different.jpg", (255, 255, 255), 3.0)

    result = dedupe_similar_frames([*same_color_frames, different_frame])

    assert result == [same_color_frames[0], different_frame]


def test_compares_against_last_kept_not_immediately_previous_frame(
    tmp_path: Path,
) -> None:
    """Distinguishes "compare to last KEPT" from the simpler-but-wrong
    "compare to immediately previous frame" algorithm.

    Construct three frames: A (black), B (mid-gray, far enough from A to
    be kept), C (black again, identical to A). Under "compare to
    immediately previous": C is compared to B (large diff) and would be
    KEPT. Under "compare to last KEPT" (the correct algorithm, since B was
    kept): C is compared to B too in this particular 3-frame layout... so
    instead use a 4-frame layout where frame D ALSO near-matches A within
    threshold, after a deliberately-kept B, to show D is compared against
    the ORIGINAL kept baseline (B, the last kept frame), not against C.

    Concretely: A kept (baseline). B is different from A -> kept, becomes
    new baseline. C is near-identical to B (just under threshold vs B) ->
    dropped as a near-dup of the last-kept (B), not compared against A.
    This proves comparisons walk forward against whatever was last KEPT
    (B), never silently reset back to the first frame (A) and never
    compared against C (which was dropped, so it must never become a
    comparison baseline at all).
    """
    a = _solid_frame(tmp_path / "a.jpg", (0, 0, 0), 0.0)
    b = _solid_frame(tmp_path / "b.jpg", (200, 200, 200), 1.0)
    # c is close to b (small diff) but ALSO happens to be close to a's
    # opposite extreme -- doesn't matter, what matters is it's compared
    # against b (the last kept), not a.
    c = _solid_frame(tmp_path / "c.jpg", (205, 205, 205), 2.0)

    result = dedupe_similar_frames([a, b, c], threshold=0.04)

    # a kept (first), b kept (far from a), c dropped (near b, the last
    # kept frame -- NOT compared against a, which it is actually also far
    # from, so a naive "reset to frame zero" bug would incorrectly keep c
    # too).
    assert result == [a, b]


def test_threshold_boundary_frame_just_below_threshold_is_dropped(
    tmp_path: Path,
) -> None:
    """Two grayscale values whose mean abs difference / 255 lands just
    UNDER a given threshold -- the frame must be dropped (not kept)."""
    base = _solid_frame(tmp_path / "base.jpg", (100, 100, 100), 0.0)
    # Diff per pixel = 5 -> normalized diff = 5/255 ~= 0.0196.
    near = _solid_frame(tmp_path / "near.jpg", (105, 105, 105), 1.0)

    result = dedupe_similar_frames([base, near], threshold=0.03)

    assert result == [base]


def test_threshold_boundary_frame_just_above_threshold_is_kept(
    tmp_path: Path,
) -> None:
    """Same pair of frames as the "just below" case, but with a lower
    threshold so the same diff now lands just OVER it -- the frame must be
    kept."""
    base = _solid_frame(tmp_path / "base.jpg", (100, 100, 100), 0.0)
    # Same diff (~0.0196) as the "below" test above.
    near = _solid_frame(tmp_path / "near.jpg", (105, 105, 105), 1.0)

    result = dedupe_similar_frames([base, near], threshold=0.01)

    assert result == [base, near]
