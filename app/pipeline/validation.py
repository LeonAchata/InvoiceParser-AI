"""Deterministic sanity checks run on top of the LLM output."""

from datetime import date
from typing import Literal

from pydantic import BaseModel

from app.schemas import InvoiceData

Status = Literal["pass", "warn", "fail"]


class Check(BaseModel):
    id: str
    label: str
    status: Status
    detail: str
    field: str | None = None


# Invoices round every line to cents, so allow a few cents of drift but nothing more.
CENTS = 0.06


def _close(a: float, b: float, tolerance: float = CENTS) -> bool:
    return abs(a - b) <= tolerance


def ruc_is_valid(ruc: str) -> bool:
    """SUNAT RUC check digit (modulo 11)."""
    if len(ruc) != 11 or not ruc.isdigit() or ruc[:2] not in ("10", "15", "16", "17", "20"):
        return False
    weights = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
    digit = 11 - sum(int(d) * w for d, w in zip(ruc[:10], weights)) % 11
    return int(ruc[10]) == {10: 0, 11: 1}.get(digit, digit)


def _tax_id_check(role: str, tax_id: str | None) -> Check | None:
    if not tax_id:
        return None
    digits = "".join(ch for ch in tax_id if ch.isdigit())
    field = f"{role}.tax_id"
    label = f"{role.capitalize()} tax ID"
    if len(digits) == 11 and digits == tax_id.strip():
        if ruc_is_valid(digits):
            return Check(id=f"{role}_ruc", label=label, status="pass", detail=f"Valid RUC {digits}", field=field)
        return Check(
            id=f"{role}_ruc", label=label, status="warn", detail=f"RUC {digits} has an invalid check digit", field=field
        )
    if len(digits) == 8 and digits == tax_id.strip():
        return Check(id=f"{role}_dni", label=label, status="pass", detail=f"DNI {digits}", field=field)
    return None  # foreign / other ids: nothing to verify


def _date_check(name: str, value: str | None) -> Check | None:
    if not value:
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return Check(
            id=name,
            label=name.replace("_", " ").capitalize(),
            status="warn",
            detail=f"'{value}' is not a valid YYYY-MM-DD date",
            field=name,
        )
    if parsed > date.today() and name == "issue_date":
        return Check(id=name, label="Issue date", status="warn", detail="Issue date is in the future", field=name)
    return None


def run_checks(data: InvoiceData) -> list[Check]:
    checks: list[Check] = []
    items = [i for i in data.items if i.amount is not None]

    # Line items: quantity x unit price = amount
    bad_lines = [
        n
        for n, i in enumerate(data.items, 1)
        if None not in (i.quantity, i.unit_price, i.amount) and not _close(i.quantity * i.unit_price, i.amount)
    ]
    if data.items:
        checks.append(
            Check(
                id="line_math",
                label="Line items math",
                field="items",
                status="warn" if bad_lines else "pass",
                detail=f"qty × unit price ≠ amount on line(s) {', '.join(map(str, bad_lines))}"
                if bad_lines
                else f"{len(data.items)} line item(s) add up",
            )
        )

    # Sum of lines = subtotal (lines may be tax-inclusive, e.g. boletas, so also accept the total)
    discount = data.discount or 0
    if items and data.subtotal is not None:
        lines_sum = round(sum(i.amount for i in items), 2)
        candidates = [data.subtotal, data.subtotal + discount] + ([data.total] if data.total is not None else [])
        ok = any(_close(lines_sum, c, CENTS + 0.01 * len(items)) for c in candidates)
        checks.append(
            Check(
                id="items_sum",
                label="Items vs subtotal",
                field="subtotal",
                status="pass" if ok else "warn",
                detail=f"Items sum {lines_sum:,.2f}" + ("" if ok else f" but subtotal is {data.subtotal:,.2f}"),
            )
        )

    # Subtotal + tax = total
    if None not in (data.subtotal, data.tax, data.total):
        expected = round(data.subtotal + data.tax, 2)
        # The subtotal may be stated before or after the discount.
        if discount and not _close(expected, data.total):
            expected = round(expected - discount, 2)
        ok = _close(expected, data.total)
        label = "Subtotal − discount + tax = total" if discount else "Subtotal + tax = total"
        checks.append(
            Check(
                id="total_math",
                label=label,
                field="total",
                status="pass" if ok else "fail",
                detail=f"Expected {expected:,.2f}" + ("" if ok else f", document says {data.total:,.2f}"),
            )
        )

    # Effective tax rate
    if data.subtotal and data.tax is not None:
        stated = data.tax_rate
        bases = [data.subtotal] + ([data.subtotal - discount] if discount and data.subtotal > discount else [])
        if stated is None:
            ok, rate = True, round(data.tax / bases[-1] * 100, 2)
        else:
            # Compare amounts, not percentages: the tax must equal base × rate up to rounding.
            base = min(bases, key=lambda b: abs(b * stated / 100 - data.tax))
            ok = _close(base * stated / 100, data.tax)
            rate = round(data.tax / base * 100, 2)
        checks.append(
            Check(
                id="tax_rate",
                label="Tax rate",
                field="tax",
                status="pass" if ok else "warn",
                detail=f"Effective rate {rate:g}%" + ("" if ok else f", document states {stated:g}%"),
            )
        )

    # Withholding (detracción) amount vs percentage
    w = data.withholding
    if w and w.percentage and w.amount is not None and data.total:
        expected = data.total * w.percentage / 100
        ok = abs(expected - w.amount) <= 1.0  # SUNAT rounds detracciones to whole units
        checks.append(
            Check(
                id="withholding",
                label="Withholding",
                field="withholding",
                status="pass" if ok else "warn",
                detail=f"{w.percentage:g}% of total = {expected:,.2f}"
                + ("" if ok else f" (document says {w.amount:,.2f})"),
            )
        )

    for role, party in (("issuer", data.issuer), ("customer", data.customer)):
        if check := _tax_id_check(role, party.tax_id):
            checks.append(check)

    for name in ("issue_date", "due_date"):
        if check := _date_check(name, getattr(data, name)):
            checks.append(check)

    return checks


KEY_FIELDS = (
    "document_type",
    "document_number",
    "issue_date",
    "currency",
    "issuer.name",
    "issuer.tax_id",
    "customer.name",
    "customer.tax_id",
    "items",
    "subtotal",
    "tax",
    "total",
)


def completeness(data: InvoiceData) -> float:
    filled = 0
    for path in KEY_FIELDS:
        value = data
        for part in path.split("."):
            value = getattr(value, part)
        filled += bool(value) or value == 0
    return round(filled / len(KEY_FIELDS), 2)
