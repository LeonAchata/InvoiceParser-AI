"""PDF -> native text when available, rendered page images for scanned documents."""

import pymupdf as fitz
from PIL import Image

from app.loaders.base import LoadedDocument, UnsupportedFormatError
from app.loaders.image import normalize_image

# Below this many alphanumeric characters per page we treat the PDF as scanned.
MIN_CHARS_PER_PAGE = 40
RENDER_DPI = 170


def load_pdf(data: bytes, fmt: str, *, max_pages: int, max_side: int, **_) -> LoadedDocument:
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise UnsupportedFormatError(f"Invalid or corrupted PDF: {exc}") from exc

    with doc:
        if doc.needs_pass:
            raise UnsupportedFormatError("Password-protected PDFs are not supported")
        if doc.page_count == 0:
            raise UnsupportedFormatError("The PDF has no pages")

        pages = min(doc.page_count, max_pages)
        texts = [doc[i].get_text("text", sort=True).strip() for i in range(pages)]
        meaningful = sum(ch.isalnum() for text in texts for ch in text)
        meta = {k: v for k, v in (doc.metadata or {}).items() if v}
        meta["total_pages"] = doc.page_count

        if meaningful >= MIN_CHARS_PER_PAGE * pages:
            text = "\n\n".join(f"--- Page {i + 1} ---\n{t}" for i, t in enumerate(texts) if t)
            return LoadedDocument(format=fmt, text=text, pages=pages, method="native-text", meta=meta)

        # Scanned / image-only PDF: render each page and let the vision model read it.
        images = []
        for i in range(pages):
            pix = doc[i].get_pixmap(dpi=RENDER_DPI)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            images.append(normalize_image(img, max_side))

        return LoadedDocument(format=fmt, images=images, pages=pages, method="vision (scanned PDF)", meta=meta)
