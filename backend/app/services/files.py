"""Checks on uploaded invoice files. The browser's content type is not trusted."""

MAX_BYTES = 10 * 1024 * 1024

# Magic bytes -> (content type, file extension)
_SIGNATURES = {
    b"%PDF-": ("application/pdf", "pdf"),
    b"\x89PNG\r\n\x1a\n": ("image/png", "png"),
    b"\xff\xd8\xff": ("image/jpeg", "jpg"),
}


class InvalidFile(ValueError):
    pass


def sniff(data: bytes) -> tuple[str, str]:
    """Return (content type, extension) from the file's first bytes, or raise InvalidFile."""
    if not data:
        raise InvalidFile("The file is empty")
    if len(data) > MAX_BYTES:
        raise InvalidFile("Files must be 10 MB or smaller")
    for magic, kind in _SIGNATURES.items():
        if data.startswith(magic):
            return kind
    raise InvalidFile("Upload a PDF, PNG or JPEG file")
