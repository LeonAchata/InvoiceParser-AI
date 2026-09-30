import os
import tempfile
from pathlib import Path

import pytest

# Configure the app before it is imported: fake key, throwaway database.
os.environ["OPENAI_API_KEY"] = "sk-test"
os.environ["DATABASE_PATH"] = str(Path(tempfile.mkdtemp()) / "test.db")

SAMPLES = Path(__file__).resolve().parent.parent / "samples"

FAKE_EXTRACTION = {
    "document_type": "factura",
    "document_number": "F001-00004821",
    "issue_date": "2026-08-14",
    "currency": "S/",
    "payment_method": "Crédito",
    "issuer": {"tax_id": "20609876540", "name": "ANDES CLOUD SOLUTIONS S.A.C."},
    "customer": {"tax_id": "20555123451", "name": "COMERCIAL LOS PORTALES DEL SUR E.I.R.L.", "city": "LA MOLINA"},
    "items": [
        {"description": "Implementación ERP", "quantity": 1, "unit_price": "4,500.00", "amount": 4500},
        {"description": "Licencia mensual", "quantity": 12, "unit_price": 85, "amount": 1020},
        {"description": "Capacitación", "quantity": 8, "unit_price": 60, "amount": 480},
    ],
    "subtotal": 6000,
    "tax": 1080,
    "tax_rate": 18,
    "total": "7,080.00",
    "withholding": {"percentage": 12, "amount": 850},
}


@pytest.fixture
def sample():
    return lambda name: (SAMPLES / name).read_bytes()


@pytest.fixture
def fake_llm(monkeypatch):
    """Replace the OpenAI call; records what the pipeline sent."""
    calls = []

    async def fake(doc, text):
        calls.append({"doc": doc, "text": text})
        return dict(FAKE_EXTRACTION), {"prompt": 100, "completion": 50, "total": 150}

    monkeypatch.setattr("app.pipeline.graph.extract_with_llm", fake)
    return calls
