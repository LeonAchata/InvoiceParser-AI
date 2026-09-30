"""Structured data returned by the extractor."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

DocumentType = Literal["INVOICE", "RECEIPT", "CREDIT_NOTE", "DEBIT_NOTE", "TICKET", "OTHER"]
PAYMENT_METHODS = ["CASH", "CREDIT", "CARD", "TRANSFER", "YAPE", "PLIN", "OTHER"]


def parse_amount(value):
    """Turn things like 'S/ 1,500.00', '1.500,00' or '$20' into a float. Returns None when impossible."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = re.sub(r"[^\d,.\-]", "", str(value))
    if not text or not re.search(r"\d", text):
        return None
    if "," in text and "." in text:
        # Whichever separator appears last is the decimal separator.
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        head, _, tail = text.rpartition(",")
        text = f"{head.replace(',', '')}.{tail}" if len(tail) in (1, 2) else text.replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    @field_validator("*", mode="before")
    @classmethod
    def blank_to_none(cls, v):
        if isinstance(v, str) and v.strip().lower() in ("", "null", "none", "n/a", "-"):
            return None
        return v


class Party(_Model):
    tax_id: str | None = Field(default=None, description="RUC, DNI, VAT or other tax id")
    name: str | None = None
    address: str | None = None
    city: str | None = Field(default=None, description="District / city")

    @field_validator("tax_id", mode="before")
    @classmethod
    def stringify(cls, v):
        return str(v) if isinstance(v, (int, float)) else v


class LineItem(_Model):
    description: str | None = None
    quantity: float | None = None
    unit_price: float | None = None
    amount: float | None = None

    @field_validator("quantity", "unit_price", "amount", mode="before")
    @classmethod
    def amounts(cls, v):
        return parse_amount(v)


class Withholding(_Model):
    """Peruvian 'detracción' or any other withholding stated on the document."""

    percentage: float | None = None
    amount: float | None = None

    @field_validator("percentage", "amount", mode="before")
    @classmethod
    def amounts(cls, v):
        return parse_amount(v)


class InvoiceData(_Model):
    document_type: DocumentType | None = None
    document_number: str | None = None
    issue_date: str | None = Field(default=None, description="YYYY-MM-DD")
    due_date: str | None = Field(default=None, description="YYYY-MM-DD")
    currency: str | None = Field(default=None, description="ISO 4217 code")
    payment_method: str | None = None
    issuer: Party = Field(default_factory=Party)
    customer: Party = Field(default_factory=Party)
    items: list[LineItem] = Field(default_factory=list)
    subtotal: float | None = None
    tax: float | None = None
    tax_rate: float | None = Field(default=None, description="Percentage, e.g. 18")
    discount: float | None = None
    total: float | None = None
    withholding: Withholding | None = None
    notes: str | None = None

    @field_validator("subtotal", "tax", "tax_rate", "discount", "total", mode="before")
    @classmethod
    def amounts(cls, v):
        return parse_amount(v)

    @field_validator("document_type", mode="before")
    @classmethod
    def normalize_type(cls, v):
        if not v:
            return None
        v = str(v).upper().replace(" ", "_")
        aliases = {"FACTURA": "INVOICE", "BOLETA": "RECEIPT", "NOTA_DE_CREDITO": "CREDIT_NOTE"}
        v = aliases.get(v, v)
        return v if v in DocumentType.__args__ else "OTHER"

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, v):
        if not v:
            return None
        v = str(v).strip().upper()
        return {"S/": "PEN", "S/.": "PEN", "SOLES": "PEN", "$": "USD", "US$": "USD", "€": "EUR"}.get(v, v)

    @field_validator("payment_method", mode="before")
    @classmethod
    def normalize_payment(cls, v):
        if not v:
            return None
        v = str(v).strip().upper()
        aliases = {
            "CONTADO": "CASH",
            "EFECTIVO": "CASH",
            "CREDITO": "CREDIT",
            "CRÉDITO": "CREDIT",
            "TARJETA": "CARD",
            "TRANSFERENCIA": "TRANSFER",
            "DEPOSITO": "TRANSFER",
        }
        return aliases.get(v, v)

    @field_validator("items", mode="before")
    @classmethod
    def none_items(cls, v):
        return v or []
