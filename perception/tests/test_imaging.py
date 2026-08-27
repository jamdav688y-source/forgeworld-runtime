import struct
import unittest
import zlib

from perception.src.imaging import (
    UnsupportedPNGError,
    _paeth,
    decode_png,
    hamming_distance,
    perceptual_fingerprint,
)
from perception.tests.base import fixture_path, load_fixture_bytes


def _chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def _encode_filter(row, prev_row, channels, filter_type):
    stride = len(row)
    out = bytearray(stride)
    if filter_type == 0:
        out[:] = row
    elif filter_type == 1:
        for i in range(stride):
            left = row[i - channels] if i >= channels else 0
            out[i] = (row[i] - left) & 0xFF
    elif filter_type == 2:
        for i in range(stride):
            out[i] = (row[i] - prev_row[i]) & 0xFF
    elif filter_type == 3:
        for i in range(stride):
            left = row[i - channels] if i >= channels else 0
            out[i] = (row[i] - ((left + prev_row[i]) // 2)) & 0xFF
    elif filter_type == 4:
        for i in range(stride):
            left = row[i - channels] if i >= channels else 0
            up = prev_row[i]
            up_left = prev_row[i - channels] if i >= channels else 0
            out[i] = (row[i] - _paeth(left, up, up_left)) & 0xFF
    return out


def _make_png(width, height, pixel_fn, filter_type=0, color_type=2):
    channels = {0: 1, 2: 3, 6: 4}[color_type]
    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    raw = bytearray()
    prev_row = bytearray(width * channels)
    for y in range(height):
        row = bytearray()
        for x in range(width):
            row.extend(pixel_fn(x, y)[:channels])
        encoded = _encode_filter(row, prev_row, channels, filter_type)
        raw.append(filter_type)
        raw.extend(encoded)
        prev_row = row
    idat = zlib.compress(bytes(raw), 9)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")


def _checker(x, y):
    v = 255 if (x // 4 + y // 4) % 2 == 0 else 0
    return (v, v, v, 255)


class TestPNGDecoder(unittest.TestCase):
    def test_all_five_filter_types_decode_identically(self):
        baseline = decode_png(_make_png(16, 16, _checker, filter_type=0))[3]
        for ft in range(5):
            with self.subTest(filter_type=ft):
                pixels = decode_png(_make_png(16, 16, _checker, filter_type=ft))[3]
                self.assertEqual(bytes(pixels), bytes(baseline))

    def test_grayscale_and_rgba_color_types(self):
        w, h, ch, _ = decode_png(_make_png(8, 8, _checker, color_type=0))
        self.assertEqual((w, h, ch), (8, 8, 1))
        w, h, ch, _ = decode_png(_make_png(8, 8, _checker, color_type=6))
        self.assertEqual((w, h, ch), (8, 8, 4))

    def test_bad_signature_raises(self):
        with self.assertRaises(UnsupportedPNGError):
            decode_png(b"definitely not a png")

    def test_16bit_depth_raises(self):
        ihdr = struct.pack(">IIBBBBB", 4, 4, 16, 2, 0, 0, 0)
        bad = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IEND", b"")
        with self.assertRaises(UnsupportedPNGError):
            decode_png(bad)

    def test_real_screenshot_fixture_decodes_with_matching_byte_count(self):
        data = load_fixture_bytes("screenshot_1554.png")
        w, h, ch, pixels = decode_png(data)
        self.assertEqual(len(pixels), w * h * ch)
        self.assertFalse(all(b == 0 for b in pixels))


class TestPerceptualFingerprint(unittest.TestCase):
    def test_deterministic(self):
        data = _make_png(32, 32, _checker)
        self.assertEqual(perceptual_fingerprint(data), perceptual_fingerprint(data))

    def test_near_duplicate_vs_genuinely_different(self):
        def noisy(x, y):
            v = 255 if (x // 4 + y // 4) % 2 == 0 else 0
            if x == 0 and y == 0:
                v = min(255, v + 10)
            return (v, v, v, 255)

        def inverted(x, y):
            v = 0 if (x // 4 + y // 4) % 2 == 0 else 255
            return (v, v, v, 255)

        fp_base = perceptual_fingerprint(_make_png(32, 32, _checker))
        fp_near = perceptual_fingerprint(_make_png(32, 32, noisy))
        fp_diff = perceptual_fingerprint(_make_png(32, 32, inverted))

        self.assertEqual(hamming_distance(fp_base, fp_near), 0)
        self.assertGreater(hamming_distance(fp_base, fp_diff), hamming_distance(fp_base, fp_near))

    def test_hamming_distance_requires_equal_length(self):
        with self.assertRaises(ValueError):
            hamming_distance("ab", "abcd")

    def test_fixture_1554_and_1555_are_near_duplicates_with_different_bytes(self):
        b1554 = load_fixture_bytes("screenshot_1554.png")
        b1555 = load_fixture_bytes("screenshot_1555.png")
        bdiff = load_fixture_bytes("screenshot_different.png")
        self.assertNotEqual(b1554, b1555)

        fp_1554, fp_1555, fp_diff = (perceptual_fingerprint(b) for b in (b1554, b1555, bdiff))
        self.assertEqual(hamming_distance(fp_1554, fp_1555), 0)
        self.assertGreater(hamming_distance(fp_1554, fp_diff), hamming_distance(fp_1554, fp_1555))


if __name__ == "__main__":
    unittest.main()
