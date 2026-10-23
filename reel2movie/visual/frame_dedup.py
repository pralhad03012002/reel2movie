"""Drop frames that are near-duplicates of the last KEPT frame.

Motivation (see this subtask's `PROGRESS.md` entry): dense 1-frame-per-second
sampling (`frame_sampler.sample_frames_at_interval`) is good for catching
transient on-screen text that sparse sampling can skip entirely, but a long
static shot (a held poster, a talking-head segment, a paused frame) now
produces many near-identical frames in a row. Running an expensive Claude
vision call (`visual.vision_llm_detector.VisionLLMPosterDetector.detect`) on
every single one of those would burn N calls to learn the same thing N
times. This module is a cheap, local, pre-filter that runs BEFORE any vision
call: Pillow-only, no ffmpeg/subprocess, no network.

Algorithm (deliberately "compare to the last KEPT frame", not "compare to
the immediately-previous frame"): each candidate frame, in timestamp order,
is compared only against whatever was most recently decided to be worth
keeping. This is the detail that makes a long static run collapse down to
exactly one kept frame instead of one every two frames: if candidate N is
judged "basically the same as what's already kept" and dropped, candidate
N+1 is then compared against that SAME last-kept frame again (not against
the just-dropped candidate N) -- so a slow, gradual drift across many
frames that never individually crosses the threshold against its immediate
neighbor still can't quietly sneak past this filter one small step at a
time without ever being compared to the original kept frame it has, by now,
drifted far away from.

Fingerprint: grayscale (`.convert("L")`), downscaled to a fixed small size
(`.resize((64, 64))`) so the comparison is cheap and robust to minor
encoding noise, then compared via `PIL.ImageChops.difference()` +
`PIL.ImageStat.Stat(...).mean[0] / 255.0` -- a single float in `[0, 1]`
representing the mean absolute per-pixel grayscale difference between the
two fingerprints. `>= threshold` means "different enough to keep";
`< threshold` means "near-duplicate, drop it".

`threshold=0.04` is a DELIBERATELY UNVALIDATED starting point, not a tuned
constant: it has not been run against any real reel footage yet. The
orchestrating conversation plans to empirically validate/adjust this value
against real reels once this subtask lands -- treat it as a placeholder a
reviewer should expect to see revisited, not as settled science.
"""

from __future__ import annotations

from PIL import Image, ImageChops, ImageStat

from reel2movie.core.models import FrameSample

# See module docstring: not yet empirically tuned against real reel
# footage. A deliberate starting guess, expected to be revisited.
_DEFAULT_THRESHOLD = 0.04

# Fingerprint size: small enough to make the diff cheap, large enough that
# a genuinely different frame (e.g. a new on-screen text card appearing)
# still shows up as a real difference after downscaling.
_FINGERPRINT_SIZE = (64, 64)


def _fingerprint(path) -> Image.Image:
    """Open `path`, convert to a small grayscale "L" image, detached from disk.

    Opened via `with Image.open(path) as img:` so the file handle is
    closed immediately rather than kept open for as long as the returned
    image is alive -- important here since this function may be called
    dozens of times in a row (once per sampled frame) and leaking a file
    handle per call would add up. `.copy()` on the resized image detaches
    it from the (about to be closed) underlying file-backed image object,
    since Pillow's lazy loading means the resized image could otherwise
    still reference data from a file that's no longer open.
    """
    with Image.open(path) as img:
        return img.convert("L").resize(_FINGERPRINT_SIZE).copy()


def _mean_abs_difference(a: Image.Image, b: Image.Image) -> float:
    """Mean absolute per-pixel difference between two "L"-mode images, in [0, 1].

    `ImageChops.difference` is itself symmetric and pixelwise, and both
    inputs are single-band ("L") images, so `Stat(...).mean[0]` is the one
    and only mean value there is to take (no multi-band averaging
    ambiguity to worry about). Dividing by 255 rescales from the raw 0-255
    grayscale difference range down to the `[0, 1]` scale `threshold` is
    expressed in.
    """
    diff = ImageChops.difference(a, b)
    return ImageStat.Stat(diff).mean[0] / 255.0


def dedupe_similar_frames(
    frames: list[FrameSample],
    threshold: float = _DEFAULT_THRESHOLD,
) -> list[FrameSample]:
    """Drop frames that are near-duplicates of the last KEPT frame.

    `frames[0]` is always kept unconditionally (there's nothing earlier to
    compare it to, and an empty `frames` list returns `[]` outright). Every
    later frame, in the order given, is compared only against the
    fingerprint of whatever was most recently decided to be worth keeping
    (not the immediately-previous frame -- see the module docstring for why
    this distinction matters). A frame whose mean absolute pixel difference
    against that last-kept fingerprint is `>= threshold` is genuinely
    different: it's kept, and it becomes the new comparison baseline for
    subsequent frames. Otherwise it's dropped as a near-duplicate of
    content already represented in the kept set.

    This function does no I/O beyond opening each frame's image file once
    (via Pillow) -- no ffmpeg, no subprocess, no network call, and
    critically no Claude vision call: it's meant to run entirely BEFORE any
    `PosterDetector.detect()` call, trimming the frame list down first.
    """
    if not frames:
        return []

    kept: list[FrameSample] = [frames[0]]
    last_kept_fingerprint = _fingerprint(frames[0].path)

    for frame in frames[1:]:
        candidate_fingerprint = _fingerprint(frame.path)
        difference = _mean_abs_difference(last_kept_fingerprint, candidate_fingerprint)
        if difference >= threshold:
            kept.append(frame)
            last_kept_fingerprint = candidate_fingerprint

    return kept
