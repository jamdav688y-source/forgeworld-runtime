"""Content/magic-byte format-detection regression coverage.

Added during a claims-integrity revision pass on PR #5, after verification
found ingest.py deriving mime_type from the filename extension rather than
actual content -- a real bug (a PNG named .jpg got mime_type=image/jpeg;
see test_extension_content_disagreement_png_as_jpg below) and two
robustness gaps (truncated PNG data raised an uncaught zlib.error/struct.error
instead of the documented IngestError contract; see
test_truncated_png_fails_closed_not_uncaught).

Every scenario here is deterministic and offline: no network, no live
external repository, no third-party imaging library -- exactly this
repo's, and this package's, established posture.
"""
import struct
import tempfile
import zlib

from perception.src import imaging, ingest
from perception.tests.base import PerceptionTestCase, fixture_path


def _make_minimal_png(width=4, height=4, color_type=2):
    """Deterministic, valid, minimal PNG -- filter type 0 throughout."""
    channels = {0: 1, 2: 3, 6: 4}[color_type]

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            raw.extend(bytes([(x * 17 + y * 31) % 256] * channels))
    idat = zlib.compress(bytes(raw), 9)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def _make_jpeg_like_bytes(n=200):
    """Real JPEG SOI marker (0xFFD8FF) + JFIF tag + deterministic filler --
    not a real, fully-formed JPEG (this codebase never needs to decode
    one), just enough to trigger content-based JPEG detection."""
    return b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + bytes((i * 7) % 256 for i in range(n))


class TestValidSupportedPNG(PerceptionTestCase):
    def test_valid_png_ingests_with_content_derived_mime_type(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(_make_minimal_png())
            path = f.name
        obs = ingest.ingest_image(path, capture_source="test")
        self.assertEqual(obs["mime_type"], "image/png")
        self.assertEqual(obs["width"], 4)
        self.assertEqual(obs["height"], 4)


class TestJPEGContentWithPNGExtension(PerceptionTestCase):
    def test_jpeg_content_named_dot_png_is_rejected_not_misdecoded(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(_make_jpeg_like_bytes())
            path = f.name
        with self.assertRaises(ingest.IngestError) as ctx:
            ingest.ingest_image(path, capture_source="test")
        self.assertIn("JPEG", str(ctx.exception))

    def test_detect_media_type_identifies_jpeg_by_content_regardless_of_extension(self):
        self.assertEqual(imaging.detect_media_type(_make_jpeg_like_bytes()), "image/jpeg")


class TestUnsupportedMedia(PerceptionTestCase):
    def test_random_bytes_are_rejected_as_unsupported_not_silently_accepted(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(bytes((i * 13) % 256 for i in range(300)))  # deterministic, not a valid image
            path = f.name
        with self.assertRaises(ingest.IngestError):
            ingest.ingest_image(path, capture_source="test")

    def test_detect_media_type_returns_octet_stream_for_unknown_content(self):
        self.assertEqual(imaging.detect_media_type(b"not an image at all"), "application/octet-stream")


class TestTruncatedOrCorruptMedia(PerceptionTestCase):
    def test_truncated_png_fails_closed_not_uncaught(self):
        full = _make_minimal_png(width=16, height=16)
        truncated = full[: len(full) // 2]  # valid signature + IHDR, IDAT cut mid-stream
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(truncated)
            path = f.name
        # Must raise the documented IngestError, never an uncaught
        # zlib.error/struct.error escaping past the module boundary.
        with self.assertRaises(ingest.IngestError):
            ingest.ingest_image(path, capture_source="test")

    def test_truncated_ihdr_chunk_fails_closed(self):
        data = imaging.PNG_SIGNATURE + b"\x00\x00\x00\x0dIHDR\x00\x01\x02"  # declares 13 bytes, gives 3
        with self.assertRaises(imaging.UnsupportedPNGError):
            imaging.decode_png(data)

    def test_truncated_idat_raises_unsupported_png_error_not_zlib_error(self):
        full = _make_minimal_png(width=32, height=32)
        # Cut deep into the compressed IDAT payload (not just the trailing
        # IEND chunk, which decode_png doesn't strictly validate) so this
        # actually exercises the zlib-truncation path, not a no-op trim.
        truncated = full[: len(full) - 400]
        with self.assertRaises(imaging.UnsupportedPNGError):
            imaging.decode_png(truncated)

    def test_zero_length_file_fails_closed(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            path = f.name
        with self.assertRaises(ingest.IngestError):
            ingest.ingest_image(path, capture_source="test")


class TestExtensionContentDisagreement(PerceptionTestCase):
    def test_extension_content_disagreement_png_as_jpg(self):
        # Regression test for the actual bug found in this revision:
        # ingest.py previously derived mime_type from the filename
        # extension, so a real PNG named .jpg got mime_type=image/jpeg.
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(_make_minimal_png())
            path = f.name
        obs = ingest.ingest_image(path, capture_source="test")
        self.assertEqual(obs["mime_type"], "image/png")  # content wins, not the .jpg extension

    def test_stored_copy_extension_reflects_detected_content_not_source_extension(self):
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(_make_minimal_png())
            path = f.name
        obs = ingest.ingest_image(path, capture_source="test")
        stored = ingest.stored_image_path(obs["source_image_sha256"])
        self.assertEqual(stored.suffix, ".png")

    def test_real_fixture_png_ingests_identically_regardless_of_source_extension(self):
        real_bytes = fixture_path("screenshot_1554.png").read_bytes()
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(real_bytes)
            renamed_path = f.name

        obs_correct_ext = ingest.ingest_image(fixture_path("screenshot_1554.png"), capture_source="test")
        obs_wrong_ext = ingest.ingest_image(renamed_path, capture_source="test")

        self.assertEqual(obs_correct_ext["source_image_sha256"], obs_wrong_ext["source_image_sha256"])
        self.assertEqual(obs_correct_ext["mime_type"], obs_wrong_ext["mime_type"])
        self.assertEqual(obs_correct_ext["width"], obs_wrong_ext["width"])
