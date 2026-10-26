#!/usr/bin/env python3
"""Generates this package's deterministic, synthetic PNG fixtures.

**On 1554.png / 1555.png**: the mission brief asks for "the supplied
screenshots corresponding to 1554.png and 1555.png". No such files exist
anywhere in this environment or repository (confirmed by exhaustive
filesystem search -- see perception/governance/00_DISCOVERY_REPORT.md's
"Fixture discrepancy" section). Rather than fabricate a claim that they
were used, this generator produces clearly-labeled *synthetic* stand-ins
that exercise the exact scenario the acceptance tests describe:

  screenshot_1554.png / screenshot_1555.png -- a near-duplicate PAIR
    (same underlying pattern, a handful of pixels perturbed, as real
    recompression/re-screenshot noise would produce). Their sha256 digests
    are, and must always be, different -- they are never the same file.
    Their perceptual fingerprints are close enough to associate as
    near_duplicate (see corroboration.compare_observation_fingerprints),
    without ever being declared identical.

  screenshot_different.png -- a genuinely different image, for the
    negative control: two screenshots that are simply not related.

Output is fully deterministic: same bytes on every run (no timestamps, no
randomness), so a fixture's sha256 is a stable constant other fixture
files (ocr_fixtures.json, retrieval_fixtures.json) can reference directly.
Run `python3 -m perception.fixtures.generate_fixtures` to (re)write them,
and `--verify` to check the on-disk files still match without rewriting.
"""
import argparse
import hashlib
import struct
import sys
import zlib
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def _encode_png(width: int, height: int, pixel_fn, color_type: int = 2) -> bytes:
    """Minimal encoder (filter type 0/None throughout) -- imaging.py's
    decoder is independently tested against all 5 filter types, so an
    encoder that only ever emits filter 0 is sufficient here and keeps
    this generator simple."""
    channels = {0: 1, 2: 3, 6: 4}[color_type]
    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter type None
        for x in range(width):
            raw.extend(pixel_fn(x, y)[:channels])
    idat = zlib.compress(bytes(raw), level=9)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")


def _mock_screenshot_pixel(x: int, y: int, width: int, height: int) -> tuple:
    """A simple synthetic "app screenshot" pattern: an 8px title bar, then
    an 8x8 checkerboard of "content cards" -- 8px cells deliberately match
    perceptual_fingerprint()'s default 8x8 sampling grid so the pattern
    actually varies at every sample point (a coarser cell size than the
    9-point grid resolves is invisible to the fingerprint -- the exact
    mistake an earlier version of this generator made: 60px cards in a
    64px image meant only one of nine sampled columns ever crossed a card
    boundary, so every fixture hashed to the same degenerate all-zero
    fingerprint). Not a photo of anything real -- an auditable,
    reproducible pattern standing in for one.
    """
    if y < 8:  # title bar
        return (30, 40, 90, 255)
    cell_x, cell_y = x // 8, (y - 8) // 8
    base = 220 if (cell_x + cell_y) % 2 == 0 else 60
    return (base, base, max(0, base - 20), 255)


def _perturb(pixel_fn, dx: int, dy: int):
    """Returns a pixel_fn that nudges a single pixel at (dx, dy) slightly,
    simulating the kind of tiny recompression/re-screenshot noise that
    makes two captures of "the same" screen byte-different but perceptually
    identical."""
    def wrapped(x, y):
        r, g, b, a = pixel_fn(x, y)
        if x == dx and y == dy:
            r = min(255, r + 12)
        return (r, g, b, a)
    return wrapped


def generate() -> dict:
    """Returns {filename: bytes} for every fixture this package defines."""
    width, height = 64, 64

    def base_pixel(x, y):
        return _mock_screenshot_pixel(x, y, width, height)

    screenshot_1554 = _encode_png(width, height, base_pixel, color_type=6)
    screenshot_1555 = _encode_png(width, height, _perturb(base_pixel, 5, 5), color_type=6)

    def different_pixel(x, y):
        # inverted checkerboard phase + different title bar hue -- genuinely
        # different content, not a recompression of the same screen.
        if y < 8:
            return (200, 30, 30, 255)
        cell_x, cell_y = x // 8, (y - 8) // 8
        base = 60 if (cell_x + cell_y) % 2 == 0 else 220
        return (base, max(0, base - 30), base, 255)

    screenshot_different = _encode_png(width, height, different_pixel, color_type=6)

    return {
        "screenshot_1554.png": screenshot_1554,
        "screenshot_1555.png": screenshot_1555,
        "screenshot_different.png": screenshot_different,
    }


def write_fixtures() -> dict:
    manifest = {}
    for name, data in generate().items():
        path = FIXTURES_DIR / name
        path.write_bytes(data)
        manifest[name] = hashlib.sha256(data).hexdigest()
    return manifest


def verify_fixtures() -> bool:
    expected = generate()
    ok = True
    for name, data in expected.items():
        path = FIXTURES_DIR / name
        if not path.exists():
            print(f"MISSING: {name}", file=sys.stderr)
            ok = False
            continue
        actual = path.read_bytes()
        if actual != data:
            print(f"DRIFTED: {name} (on-disk bytes do not match the generator)", file=sys.stderr)
            ok = False
    return ok


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        sys.exit(0 if verify_fixtures() else 1)
    manifest = write_fixtures()
    for name, digest in manifest.items():
        print(f"{digest}  {name}")
