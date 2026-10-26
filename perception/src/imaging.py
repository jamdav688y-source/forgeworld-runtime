"""Pure-stdlib PNG decoding + a simple perceptual fingerprint.

No Pillow, no third-party imaging library -- consistent with this repo's
established zero-third-party-dependency posture (see whatsapp/src/schema.py's
own reasoning: no jsonschema package either, and no requirements.txt/lockfile
exists anywhere in the repository to manage one). Only `zlib` and `struct`
(stdlib) are used.

Supports 8-bit, non-interlaced PNGs with color type 0 (grayscale), 2 (RGB),
or 6 (RGBA) -- this covers both the synthetic fixtures generated in this
package and real Android screenshots (confirmed against the one real
screenshot available in this environment: 8-bit RGBA, non-interlaced).
Anything else (16-bit, indexed/palette, interlaced) raises a clear
UnsupportedPNGError rather than silently producing a wrong fingerprint --
this is a from-scratch decoder sized to PROOF-001, not a general-purpose
image library, and it should fail loudly outside that scope.

JPEG is NOT supported. This repository has no third-party imaging
dependency and this decoder does not pretend otherwise -- see
detect_media_type() below and ingest.py's UNSUPPORTED_MEDIA path: JPEG
content is detected by magic bytes and rejected with a structured,
distinctly-labeled error, not silently mis-decoded or mis-labeled.

Hardened against truncated/corrupt input (found during a claims-integrity
revision pass on PR #5): every stdlib exception a malformed chunk stream
or a truncated zlib/IDAT payload can raise (struct.error, zlib.error,
IndexError) is caught here and re-raised as UnsupportedPNGError -- this
function's documented failure mode -- so a truncated file can never escape
as an uncaught, undocumented exception past this module's boundary.
"""
import struct
import zlib

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8\xff"


class UnsupportedPNGError(Exception):
    pass


def detect_media_type(data: bytes) -> str:
    """Content-based media-type detection -- never trusts a filename
    extension. Returns a MIME-ish string; 'image/png' only after matching
    the actual PNG magic bytes, 'image/jpeg' likewise for JPEG's SOI
    marker, 'application/octet-stream' for anything else. This is the
    single source of truth ingest.py's mime_type field is derived from."""
    if data[:8] == PNG_SIGNATURE:
        return "image/png"
    if data[:3] == JPEG_SIGNATURE:
        return "image/jpeg"
    return "application/octet-stream"


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def decode_png(data: bytes):
    """Returns (width, height, channels, pixels) where pixels is a flat
    bytearray of length width*height*channels, row-major, top-to-bottom.
    """
    if data[:8] != PNG_SIGNATURE:
        raise UnsupportedPNGError("not a PNG file (bad signature)")

    pos = 8
    width = height = bit_depth = color_type = interlace = None
    idat = bytearray()

    try:
        while pos < len(data):
            length = struct.unpack(">I", data[pos:pos + 4])[0]
            ctype = data[pos + 4:pos + 8]
            chunk_data = data[pos + 8:pos + 8 + length]
            if len(chunk_data) < length:
                raise UnsupportedPNGError(f"truncated PNG: chunk {ctype!r} declares {length} bytes but only {len(chunk_data)} are present")
            pos += 8 + length + 4  # skip CRC

            if ctype == b"IHDR":
                width, height, bit_depth, color_type, _comp, _filt, interlace = struct.unpack(
                    ">IIBBBBB", chunk_data
                )
            elif ctype == b"IDAT":
                idat.extend(chunk_data)
            elif ctype == b"IEND":
                break
    except struct.error as e:
        raise UnsupportedPNGError(f"truncated or corrupt PNG chunk structure: {e}") from e

    if width is None:
        raise UnsupportedPNGError("no IHDR chunk found")
    if bit_depth != 8:
        raise UnsupportedPNGError(f"only 8-bit PNGs are supported (got bit_depth={bit_depth})")
    if interlace != 0:
        raise UnsupportedPNGError("interlaced PNGs are not supported")
    if color_type not in (0, 2, 6):
        raise UnsupportedPNGError(f"only grayscale/RGB/RGBA PNGs are supported (got color_type={color_type})")

    channels = {0: 1, 2: 3, 6: 4}[color_type]
    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error as e:
        raise UnsupportedPNGError(f"truncated or corrupt PNG image data (zlib): {e}") from e

    stride = width * channels
    pixels = bytearray(height * stride)
    prev_row = bytearray(stride)
    offset = 0

    for y in range(height):
        if offset >= len(raw):
            raise UnsupportedPNGError(f"truncated PNG pixel data: expected {height} scanlines, ran out after row {y}")
        filter_type = raw[offset]
        offset += 1
        row = bytearray(raw[offset:offset + stride])
        if len(row) < stride:
            raise UnsupportedPNGError(f"truncated PNG scanline at row {y}: expected {stride} bytes, got {len(row)}")
        offset += stride

        if filter_type == 0:
            pass  # None
        elif filter_type == 1:  # Sub
            for i in range(channels, stride):
                row[i] = (row[i] + row[i - channels]) & 0xFF
        elif filter_type == 2:  # Up
            for i in range(stride):
                row[i] = (row[i] + prev_row[i]) & 0xFF
        elif filter_type == 3:  # Average
            for i in range(stride):
                left = row[i - channels] if i >= channels else 0
                row[i] = (row[i] + ((left + prev_row[i]) // 2)) & 0xFF
        elif filter_type == 4:  # Paeth
            for i in range(stride):
                left = row[i - channels] if i >= channels else 0
                up = prev_row[i]
                up_left = prev_row[i - channels] if i >= channels else 0
                row[i] = (row[i] + _paeth(left, up, up_left)) & 0xFF
        else:
            raise UnsupportedPNGError(f"unknown scanline filter type {filter_type}")

        pixels[y * stride:(y + 1) * stride] = row
        prev_row = row

    return width, height, channels, pixels


def _grayscale_grid(width, height, channels, pixels, grid_size):
    """Downsample to a grid_size x grid_size grayscale grid via nearest-
    neighbor sampling -- deliberately simple (no interpolation/averaging
    kernel), sized to a perceptual fingerprint for near-duplicate detection,
    not photographic-quality resizing."""
    out = [[0] * grid_size for _ in range(grid_size)]
    for gy in range(grid_size):
        sy = min(height - 1, (gy * height) // grid_size)
        for gx in range(grid_size):
            sx = min(width - 1, (gx * width) // grid_size)
            idx = (sy * width + sx) * channels
            if channels == 1:
                gray = pixels[idx]
            else:
                r, g, b = pixels[idx], pixels[idx + 1], pixels[idx + 2]
                gray = (r * 299 + g * 587 + b * 114) // 1000  # standard luma weights
            out[gy][gx] = gray
    return out


def perceptual_fingerprint(png_bytes: bytes, grid_size: int = 8) -> str:
    """Difference hash (dHash): compares each pixel to its right neighbor
    in a downsampled grayscale grid, producing a grid_size*grid_size-bit
    fingerprint as a hex string. Robust to small compression/resizing
    differences (the acceptance test's "near-duplicate... without being
    declared identical" scenario) while still changing for genuinely
    different images -- a real, if simple, perceptual hash, not a stand-in
    for the exact sha256 content hash computed separately in ingest.py.
    """
    width, height, channels, pixels = decode_png(png_bytes)
    grid = _grayscale_grid(width, height, channels, pixels, grid_size + 1)

    bits = []
    for gy in range(grid_size):
        for gx in range(grid_size):
            bits.append("1" if grid[gy][gx] > grid[gy][gx + 1] else "0")
    bitstring = "".join(bits)

    value = int(bitstring, 2)
    hex_len = (len(bitstring) + 3) // 4
    return format(value, f"0{hex_len}x")


def hamming_distance(hex_a: str, hex_b: str) -> int:
    if len(hex_a) != len(hex_b):
        raise ValueError("fingerprints must be the same length to compare")
    return bin(int(hex_a, 16) ^ int(hex_b, 16)).count("1")
