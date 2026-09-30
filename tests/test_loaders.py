from io import BytesIO

import pytest
from PIL import Image

from app.loaders import UnsupportedFormatError, detect_format, load_document


@pytest.mark.parametrize(
    "name, fmt, method, has_text, images",
    [
        ("factura-electronica.pdf", "pdf", "native-text", True, 0),
        ("factura-escaneada.pdf", "pdf", "vision (scanned PDF)", False, 1),
        ("boleta-foto.jpg", "jpeg", "vision", False, 1),
        ("invoice-northwind.docx", "docx", "native-text", True, 0),
        ("factura-mar-azul.xlsx", "xlsx", "native-text", True, 0),
        ("factura-ubl-sunat.xml", "xml", "native-text (structured XML)", True, 0),
        ("email-con-factura.eml", "eml", "email", True, 0),
    ],
)
def test_samples_load(sample, name, fmt, method, has_text, images):
    doc = load_document(sample(name), name)
    assert doc.format == fmt
    assert doc.method == method
    assert bool(doc.text.strip()) is has_text
    assert len(doc.images) == images


def test_pdf_text_contains_totals(sample):
    text = load_document(sample("factura-electronica.pdf"), "f.pdf").text
    assert "F001-00004821" in text and "7,080.00" in text


def test_docx_keeps_table_rows(sample):
    text = load_document(sample("invoice-northwind.docx"), "i.docx").text
    assert "Brand identity refresh (logo, palette, typography) | 1 | $3,200.00 | $3,200.00" in text


def test_xml_signature_is_stripped(sample):
    text = load_document(sample("factura-ubl-sunat.xml"), "f.xml").text
    assert "SignatureValue" not in text and "F010-00000315" in text


def test_email_attachment_is_loaded(sample):
    doc = load_document(sample("email-con-factura.eml"), "mail.eml")
    assert doc.meta["attachments"] == [{"filename": "F001-00004821.pdf", "format": "pdf", "method": "native-text"}]
    assert "Attachment: F001-00004821.pdf" in doc.text and "7,080.00" in doc.text


def test_csv_html_json_txt():
    assert "Widget | 2 | 10,50" in load_document(b"desc;qty;price\nWidget;2;10,50\n", "x.csv").text
    html = b"<html><style>p{}</style><body><h1>Invoice 7</h1><table><tr><td>A</td><td>1</td></tr></table></body></html>"
    html_text = load_document(html, "x.html").text
    assert "Invoice 7" in html_text and "p{}" not in html_text
    assert '"total": 5' in load_document(b'{"total":5}', "x.json").text
    assert load_document("Total: S/ 10 ñ".encode("cp1252"), "x.txt").text == "Total: S/ 10 ñ"


def test_mislabeled_image_uses_real_format():
    buffer = BytesIO()
    Image.new("RGBA", (3000, 1000), (255, 0, 0, 128)).save(buffer, format="PNG")
    png = buffer.getvalue()
    assert detect_format("photo.jpg", png) == "png"
    doc = load_document(png, "photo.jpg")
    assert doc.images[0].mime == "image/jpeg"
    assert Image.open(BytesIO(doc.images[0].data)).size == (2000, 667)  # downscaled


def test_detects_format_without_extension(sample):
    assert detect_format("upload", sample("factura-electronica.pdf")) == "pdf"
    assert detect_format("upload", sample("invoice-northwind.docx")) == "docx"
    assert detect_format("upload", sample("factura-mar-azul.xlsx")) == "xlsx"


def test_unsupported_and_corrupted():
    with pytest.raises(UnsupportedFormatError):
        load_document(b"\x00\x01binary", "file.exe")
    with pytest.raises(UnsupportedFormatError):
        load_document(b"%PDF-1.7 garbage", "broken.pdf")
