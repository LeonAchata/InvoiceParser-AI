import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import FAKE_EXTRACTION


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_health_and_formats(client):
    assert client.get("/api/health").json()["llm_configured"] is True
    formats = client.get("/api/formats").json()["formats"]
    exts = {e for f in formats for e in f["extensions"]}
    assert {".pdf", ".jpg", ".docx", ".xlsx", ".xml", ".eml", ".heic"} <= exts


def test_frontend_and_samples_are_served(client):
    assert "InvoiceParser" in client.get("/").text
    assert client.get("/app.js").status_code == 200
    samples = client.get("/api/samples").json()
    assert len(samples) >= 5
    assert client.get(samples[0]["url"]).status_code == 200


def test_extract_end_to_end(client, sample, fake_llm):
    files = {"file": ("factura.pdf", sample("factura-electronica.pdf"), "application/pdf")}
    job = client.post("/api/extract?wait=true", files=files).json()
    assert job["status"] == "completed", job["error"]
    result = job["result"]
    assert result["data"]["total"] == 7080.0
    assert result["data"]["currency"] == "PEN"
    assert result["document"]["method"] == "native-text"
    assert all(c["status"] == "pass" for c in result["checks"])
    assert set(result["timings"]) == {"load", "clean", "extract", "validate"}
    assert "F001-00004821" in fake_llm[0]["text"]
    assert client.get(f"/api/jobs/{job['id']}").json()["status"] == "completed"


def test_scanned_pdf_goes_to_vision(client, sample, fake_llm):
    files = {"file": ("scan.pdf", sample("factura-escaneada.pdf"), "application/pdf")}
    job = client.post("/api/extract?wait=true", files=files).json()
    assert job["status"] == "completed"
    assert job["result"]["document"]["images_sent"] == 1
    assert fake_llm[0]["text"] == ""


def test_extract_rejects_bad_input(client):
    assert (
        client.post("/api/extract", files={"file": ("a.exe", b"MZ\x00", "application/octet-stream")}).status_code == 415
    )
    assert client.post("/api/extract", files={"file": ("a.pdf", b"", "application/pdf")}).status_code == 400
    assert client.get("/api/jobs/nope").status_code == 404


def test_failed_job_reports_error(client, fake_llm):
    files = {"file": ("broken.pdf", b"%PDF-1.4 nope", "application/pdf")}
    job = client.post("/api/extract?wait=true", files=files).json()
    assert job["status"] == "failed"
    assert "PDF" in job["error"]


def test_history_and_excel(client):
    payload = {"data": FAKE_EXTRACTION, "filename": "factura.pdf"}
    doc_id = client.post("/api/documents", json=payload).json()["id"]
    listed = client.get("/api/documents").json()["items"]
    assert listed[0]["id"] == doc_id and listed[0]["total"] == 7080.0
    assert client.get(f"/api/documents/{doc_id}").json()["data"]["issuer"]["name"].startswith("ANDES")

    xlsx = client.post("/api/export/xlsx", json=payload)
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"
    assert "factura_" in xlsx.headers["content-disposition"]

    assert client.delete(f"/api/documents/{doc_id}").status_code == 204
    assert client.get(f"/api/documents/{doc_id}").status_code == 404
