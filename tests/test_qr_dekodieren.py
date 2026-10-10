"""Tests für die reine QR-Dekodierung (tests/e2e/schritte.qr_dekodieren)."""

import sys
from io import BytesIO
from pathlib import Path

import segno

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.e2e.schritte import qr_dekodieren


def test_qr_dekodieren_liest_url() -> None:
    url = "https://example.test/handy?k=abc&meeting=xyz"
    buf = BytesIO()
    segno.make(url).save(buf, kind="png", scale=4)
    assert qr_dekodieren(buf.getvalue()) == url


def test_qr_dekodieren_leeres_weisses_png() -> None:
    import struct
    import zlib

    def chunk(typ: bytes, daten: bytes) -> bytes:
        block = typ + daten
        return struct.pack(">I", len(daten)) + block + struct.pack(">I", zlib.crc32(block) & 0xffffffff)

    breite = hoehe = 100
    zeilen = b"".join(b"\x00" + b"\xff" * breite for _ in range(hoehe))
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", breite, hoehe, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(zeilen))
        + chunk(b"IEND", b"")
    )
    assert qr_dekodieren(png) == ""
