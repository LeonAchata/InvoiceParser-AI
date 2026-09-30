"""Raster images (PNG, JPG, WEBP, GIF, BMP, TIFF, HEIC) -> normalized images for a vision model."""

from io import BytesIO

from PIL import Image, ImageOps

from app.loaders.base import ImagePart, LoadedDocument, UnsupportedFormatError

try:  # HEIC/HEIF (iPhone photos) is optional.
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:  # pragma: no cover
    pass


def normalize_image(img: Image.Image, max_side: int) -> ImagePart:
    """Fix EXIF rotation, flatten transparency, downscale and encode as JPEG/PNG."""
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        rgba = img.convert("RGBA")
        img = Image.new("RGB", rgba.size, "white")
        img.paste(rgba, mask=rgba.split()[-1])
    elif img.mode != "RGB":
        img = img.convert("RGB")
    img.thumbnail((max_side, max_side), Image.LANCZOS)

    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=88, optimize=True)
    return ImagePart(mime="image/jpeg", data=buffer.getvalue())


def load_image(data: bytes, fmt: str, *, max_side: int, max_pages: int, **_) -> LoadedDocument:
    try:
        img = Image.open(BytesIO(data))
    except Exception as exc:
        raise UnsupportedFormatError(f"Could not read image: {exc}") from exc

    # Multi-page TIFF scans -> one image per page. Animated GIFs only use their first frame.
    frames = getattr(img, "n_frames", 1)
    count = 1 if fmt == "gif" else min(frames, max_pages)
    images = []
    for i in range(count):
        img.seek(i)
        images.append(normalize_image(img.copy(), max_side))

    return LoadedDocument(
        format=fmt,
        images=images,
        pages=len(images),
        method="vision",
        meta={"width": img.width, "height": img.height, "frames": frames},
    )
