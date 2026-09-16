"""services.images — moved verbatim from api_server.py (modularize-api-server)."""

_IMAGE_SIGNATURES = (
    (b"\xff\xd8\xff", "jpeg"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
    (b"BM", "bmp"),
    (b"II*\x00", "tiff"),
    (b"MM\x00*", "tiff"),
)


def sniff_image_type(data: bytes):
    """
    Identify an image format from its leading bytes.

    Replaces imghdr.what(), which was removed from the standard library in
    Python 3.13. Returns the same lowercase format names, and None when the
    data isn't a format we recognise, so the caller's Content-Type fallback
    still runs.

    Args:
        data (bytes): The start of the image file

    Returns:
        Optional[str]: Format name such as 'jpeg', or None if unrecognised
    """
    if not data:
        return None

    # WebP is a RIFF container, so the marker is not at the start.
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"

    for signature, name in _IMAGE_SIGNATURES:
        if data.startswith(signature):
            return name

    return None
