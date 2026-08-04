"""Portable hashes for frozen textual fixtures and source files."""
from __future__ import annotations

import hashlib
from pathlib import Path


def canonical_text_sha256(path: Path) -> str:
    """Hash text bytes after canonicalizing only CRLF line endings to LF."""
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest().upper()
