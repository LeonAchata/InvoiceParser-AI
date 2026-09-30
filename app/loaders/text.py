"""Text-based formats: TXT/MD, HTML, XML (UBL e-invoices), JSON and e-mails (.eml)."""

import json
import re
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser

from app.loaders.base import LoadedDocument


def decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


class _HTMLText(HTMLParser):
    BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section", "article"}
    SKIP = {"script", "style", "head", "noscript", "svg"}

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")
        elif tag in ("td", "th"):
            self.parts.append(" | ")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _HTMLText()
    parser.feed(html)
    text = "".join(parser.parts)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n\s*(\|\s*)?", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def load_plain_text(data: bytes, fmt: str, **_) -> LoadedDocument:
    return LoadedDocument(format=fmt, text=decode_text(data))


def load_html(data: bytes, fmt: str, **_) -> LoadedDocument:
    return LoadedDocument(format=fmt, text=html_to_text(decode_text(data)))


def load_xml(data: bytes, fmt: str, **_) -> LoadedDocument:
    """Electronic invoices (e.g. SUNAT UBL 2.1). Drop the digital signature and embedded binaries."""
    xml = decode_text(data)
    xml = re.sub(r"<(\w+:)?Signature\b.*?</(\w+:)?Signature>", "", xml, flags=re.S)
    xml = re.sub(
        r"<(\w+:)?EmbeddedDocumentBinaryObject\b.*?</(\w+:)?EmbeddedDocumentBinaryObject>", "", xml, flags=re.S
    )
    xml = re.sub(r">\s+<", ">\n<", xml)
    return LoadedDocument(format=fmt, text=xml.strip(), method="native-text (structured XML)")


def load_json(data: bytes, fmt: str, **_) -> LoadedDocument:
    text = decode_text(data)
    try:
        text = json.dumps(json.loads(text), indent=1, ensure_ascii=False)
    except json.JSONDecodeError:
        pass
    return LoadedDocument(format=fmt, text=text, method="native-text (structured JSON)")


def load_eml(data: bytes, fmt: str, **options) -> LoadedDocument:
    """E-mails: use the body and recursively load any supported attachment (PDF, images, XML...)."""
    from app.loaders import detect_format, load_document  # local import avoids a cycle

    msg = BytesParser(policy=policy.default).parsebytes(data)
    header = "\n".join(f"{h}: {msg[h]}" for h in ("From", "To", "Date", "Subject") if msg[h])

    body = msg.get_body(preferencelist=("plain", "html"))
    body_text = ""
    if body is not None:
        content = body.get_content()
        body_text = html_to_text(content) if body.get_content_type() == "text/html" else content

    doc = LoadedDocument(format=fmt, text=f"{header}\n\n{body_text}".strip(), method="email")
    attachments = []
    for part in msg.iter_attachments():
        name = part.get_filename() or "attachment"
        payload = part.get_payload(decode=True) or b""
        sub_format = detect_format(name, payload)
        if not sub_format or sub_format == "eml":
            continue
        try:
            sub = load_document(payload, name, **options)
        except Exception:
            continue
        doc.merge(sub, f"Attachment: {name}")
        attachments.append({"filename": name, "format": sub_format, "method": sub.method})

    doc.meta["attachments"] = attachments
    if any(a["method"].startswith("vision") for a in attachments):
        doc.method = "email + vision"
    return doc
