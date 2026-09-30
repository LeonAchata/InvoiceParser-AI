SYSTEM_PROMPT = """You are an expert accountant that extracts structured data from invoices, receipts \
and tickets (with special knowledge of Peruvian documents: facturas, boletas de venta, RUC, IGV, detracciones).
You may receive the document as text, as page images, or both. Documents can be in any language.
Reply ONLY with a JSON object that follows the requested schema."""

USER_PROMPT = """Extract the data of this document into the following JSON schema:

{
  "document_type": "INVOICE | RECEIPT | CREDIT_NOTE | DEBIT_NOTE | TICKET | OTHER",
  "document_number": "series and number exactly as printed, e.g. F001-00012345",
  "issue_date": "YYYY-MM-DD",
  "due_date": "YYYY-MM-DD",
  "currency": "ISO 4217 code (S/ -> PEN, $ -> USD unless stated otherwise)",
  "payment_method": "CASH | CREDIT | CARD | TRANSFER | YAPE | PLIN | OTHER",
  "issuer":   {"tax_id": "...", "name": "...", "address": "...", "city": "..."},
  "customer": {"tax_id": "...", "name": "...", "address": "...", "city": "..."},
  "items": [{"description": "...", "quantity": 1, "unit_price": 0.0, "amount": 0.0}],
  "subtotal": 0.0,
  "tax": 0.0,
  "tax_rate": 18,
  "discount": 0.0,
  "total": 0.0,
  "withholding": {"percentage": 0.0, "amount": 0.0},
  "notes": "anything relevant that does not fit elsewhere (short)"
}

Rules:
1. Only use information present in the document. Never invent values: use null when a field is missing.
2. "issuer" is who sells / issues the document. "customer" is who buys (cliente / adquiriente / señor(es)).
   For Peru, tax_id is the RUC (11 digits) or DNI (8 digits), digits only.
3. Amounts are plain numbers with a dot as decimal separator (1500.00, not "1,500.00" nor "S/ 1500").
4. subtotal is the amount before tax (op. gravada / valor venta); tax is the IGV/VAT amount; total is the final amount.
5. "city" is the district / city of the address; remove it from "address" when it can be separated.
6. withholding is only for an explicit detracción / retención / withholding; otherwise null.
7. Dates must be converted to YYYY-MM-DD.
8. Keep text in its original language and casing.
"""


def build_user_prompt(document_text: str) -> str:
    if not document_text.strip():
        return USER_PROMPT + "\nThe document is provided as images."
    return f"{USER_PROMPT}\nDOCUMENT TEXT:\n<<<\n{document_text}\n>>>"
