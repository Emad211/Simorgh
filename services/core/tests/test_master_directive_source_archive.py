from __future__ import annotations

import base64
import gzip
import hashlib
from pathlib import Path

_SOURCE_SHA256 = "c89fdecc73b4b09cd710fc35671fd16efd7ca3b5b73b27e616bebfe1e840919f"
_GZIP_SHA256 = "0bae4fc5ace99c13be3cf143e1722f1ba9e1df425acf799893cea4ecdf6f0b60"
_SOURCE_BYTES = 53_677
_GZIP_BYTES = 17_113
_BASE64_CHARS = 22_820
_EXPECTED_CHUNK_LENGTHS = [8_000, 8_000, 6_820]


def test_master_directive_source_archive_reconstructs_exact_uploaded_bytes() -> None:
    repository_root = Path(__file__).resolve().parents[3]
    archive_directory = (
        repository_root
        / "docs"
        / "reference"
        / "simorgh-master-directive-source"
    )
    parts = sorted(archive_directory.glob("part-*.b64"))

    assert [part.name for part in parts] == [
        "part-000.b64",
        "part-001.b64",
        "part-002.b64",
    ]
    encoded_parts = [part.read_text(encoding="ascii") for part in parts]
    assert [len(part) for part in encoded_parts] == _EXPECTED_CHUNK_LENGTHS

    encoded = "".join(encoded_parts)
    assert len(encoded) == _BASE64_CHARS
    compressed = base64.b64decode(encoded, validate=True)
    assert len(compressed) == _GZIP_BYTES
    assert hashlib.sha256(compressed).hexdigest() == _GZIP_SHA256

    original = gzip.decompress(compressed)
    assert len(original) == _SOURCE_BYTES
    assert hashlib.sha256(original).hexdigest() == _SOURCE_SHA256
    assert original.startswith("# دستور معماری و توسعهٔ سیمرغ".encode())
    assert original.rstrip().endswith(
        "از Hermes و OpenClaw بهتر خواهد شد.".encode()
    )
