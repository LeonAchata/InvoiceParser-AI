"""Format detection and a single entry point to turn any supported file into a LoadedDocument."""

from collections.abc import Callable
from pathlib import PurePath

from app.loaders.base import ImagePart, LoadedDocument, UnsupportedFormatError
from app.loaders.image import load_image
from app.loaders.office import load_csv, load_docx, load_xlsx
from app.loaders.pdf import load_pdf
from app.loaders.text import load_eml, load_html, load_json, load_plain_text, load_xml

Loader = Callable[..., LoadedDocument]

# format -> (loader, category, extensions)
FORMATS: dict[str, tuple[Loader, str, tuple[str, ...]]] = {
    "pdf": (load_pdf, "Documents", (".pdf",)),
    "docx": (load_docx, "Documents", (".docx", ".docm")),
    "xlsx": (load_xlsx, "Spreadsheets", (".xlsx", ".xlsm")),
    "csv": (load_csv, "Spreadsheets", (".csv",)),
    "tsv": (load_csv, "Spreadsheets", (".tsv",)),
    "png": (load_image, "Images", (".png",)),
    "jpeg": (load_image, "Images", (".jpg", ".jpeg", ".jfif")),
    "webp": (load_image, "Images", (".webp",)),
    "gif": (load_image, "Images", (".gif",)),
    "bmp": (load_image, "Images", (".bmp",)),
    "tiff": (load_image, "Images", (".tif", ".tiff")),
    "heic": (load_image, "Images", (".heic", ".heif")),
    "xml": (load_xml, "E-invoices & data", (".xml",)),
    "json": (load_json, "E-invoices & data", (".json",)),
    "html": (load_html, "Text & e-mail", (".html", ".htm")),
    "txt": (load_plain_text, "Text & e-mail", (".txt", ".md")),
    "eml": (load_eml, "Text & e-mail", (".eml",)),
}

EXTENSIONS = {ext: fmt for fmt, (_, _, exts) in FORMATS.items() for ext in exts}

_MAGIC = [
    (b"%PDF", "pdf"),
    (b"\x89PNG", "png"),
    (b"\xff\xd8\xff", "jpeg"),
    (b"GIF8", "gif"),
    (b"BM", "bmp"),
    (b"II*\x00", "tiff"),
    (b"MM\x00*", "tiff"),
]


def _sniff(data: bytes) -> str | None:
    head = data[:64]
    for magic, fmt in _MAGIC:
        if head.startswith(magic):
            return fmt
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1", b"ftyphevc"):
        return "heic"
    if head.startswith(b"PK\x03\x04"):  # zip container: tell docx from xlsx
        if b"word/" in data[:4096]:
            return "docx"
        if b"xl/" in data[:4096]:
            return "xlsx"
    stripped = head.lstrip(b"\xef\xbb\xbf \r\n\t").lower()
    if stripped.startswith(b"<?xml"):
        return "xml"
    if stripped.startswith((b"<!doctype html", b"<html")):
        return "html"
    if stripped.startswith((b"{", b"[")):
        return "json"
    return None


def detect_format(filename: str, data: bytes) -> str | None:
    """Detect by extension, falling back to magic bytes. Mislabeled images use their real format."""
    sniffed = _sniff(data)
    by_ext = EXTENSIONS.get(PurePath(filename or "").suffix.lower())
    if sniffed and by_ext and sniffed != by_ext and FORMATS[by_ext][1] == FORMATS[sniffed][1] == "Images":
        return sniffed
    return by_ext or sniffed


def load_document(data: bytes, filename: str, *, max_pages: int = 5, max_side: int = 2000) -> LoadedDocument:
    fmt = detect_format(filename, data)
    if not fmt:
        raise UnsupportedFormatError(f"Unsupported file type: {PurePath(filename).suffix or 'unknown'}")
    loader = FORMATS[fmt][0]
    doc = loader(data, fmt, max_pages=max_pages, max_side=max_side)
    doc.meta.setdefault("filename", filename)
    return doc


def supported_formats() -> list[dict]:
    groups: dict[str, list[str]] = {}
    for _, category, exts in FORMATS.values():
        groups.setdefault(category, []).extend(exts)
    return [{"category": c, "extensions": e} for c, e in groups.items()]


__all__ = [
    "FORMATS",
    "EXTENSIONS",
    "ImagePart",
    "LoadedDocument",
    "UnsupportedFormatError",
    "detect_format",
    "load_document",
    "supported_formats",
]
