from app.pipeline.validation import completeness, ruc_is_valid, run_checks
from app.schemas import InvoiceData, parse_amount
from tests.conftest import FAKE_EXTRACTION


def test_parse_amount():
    assert parse_amount("S/ 1,500.00") == 1500.0
    assert parse_amount("1.500,50") == 1500.5
    assert parse_amount("10,5") == 10.5
    assert parse_amount("1,234") == 1234.0
    assert parse_amount("$-20") == -20.0
    assert parse_amount("n/a") is None
    assert parse_amount(7) == 7.0


def test_schema_normalization():
    data = InvoiceData.model_validate(FAKE_EXTRACTION)
    assert data.document_type == "INVOICE"
    assert data.currency == "PEN"
    assert data.payment_method == "CREDIT"
    assert data.total == 7080.0
    assert data.items[0].unit_price == 4500.0
    minimal = InvoiceData.model_validate({"document_type": "boleta", "items": None, "notes": "  "})
    assert minimal.document_type == "RECEIPT" and minimal.items == [] and minimal.notes is None


def test_ruc_check_digit():
    assert ruc_is_valid("20609876540")
    assert not ruc_is_valid("20609876541")
    assert not ruc_is_valid("123")


def test_checks_pass_on_consistent_invoice():
    checks = {c.id: c for c in run_checks(InvoiceData.model_validate(FAKE_EXTRACTION))}
    assert {c.status for c in checks.values()} == {"pass"}
    assert {"line_math", "items_sum", "total_math", "tax_rate", "withholding", "issuer_ruc", "customer_ruc"} <= set(
        checks
    )


def test_checks_flag_inconsistencies():
    bad = {**FAKE_EXTRACTION, "total": 9999, "issuer": {"tax_id": "20609876541"}, "issue_date": "14/08/2026"}
    checks = {c.id: c for c in run_checks(InvoiceData.model_validate(bad))}
    assert checks["total_math"].status == "fail"
    assert checks["issuer_ruc"].status == "warn"
    assert checks["issue_date"].status == "warn"


def test_discount_is_taken_into_account():
    data = InvoiceData(
        subtotal=6400,
        discount=320,
        tax=501.6,
        tax_rate=8.25,
        total=6581.6,
        items=[{"amount": 3200}, {"amount": 2700}, {"amount": 500}],
    )
    assert [c.status for c in run_checks(data)] == ["pass"] * 4


def test_completeness():
    assert completeness(InvoiceData()) == 0
    assert completeness(InvoiceData.model_validate(FAKE_EXTRACTION)) > 0.8
