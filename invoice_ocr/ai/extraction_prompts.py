"""All Claude prompts for invoice extraction."""

EXTRACTION_PROMPT = """
You are an expert invoice data extraction system. Extract ALL of the following fields from this invoice. Return ONLY valid JSON, nothing else.

Required fields:
{
  "vendor_name": "",
  "vendor_address": "",
  "vendor_email": "",
  "vendor_phone": "",
  "invoice_number": "",
  "invoice_date": "YYYY-MM-DD",
  "due_date": "YYYY-MM-DD",
  "currency": "USD/EUR/NOK/etc",
  "subtotal": 0.00,
  "tax_amount": 0.00,
  "tax_rate": 0.00,
  "total_amount": 0.00,
  "po_number": "",
  "payment_terms": "",
  "bank_details": {
    "account_number": "",
    "routing_number": "",
    "iban": "",
    "swift": ""
  },
  "line_items": [
    {
      "description": "",
      "quantity": 0,
      "unit_price": 0.00,
      "line_total": 0.00,
      "gl_account": "",
      "tax_code": ""
    }
  ],
  "confidence_score": 0.95,
  "extraction_notes": ""
}

Rules:
- If a field is missing from the invoice, use null (not empty string)
- confidence_score should reflect your overall confidence (0.0-1.0)
- For dates, always convert to YYYY-MM-DD format
- For amounts, always use numbers (not strings)
- extraction_notes: note any ambiguous fields or low-confidence extractions
"""


def build_extraction_prompt(ocr_text: str, vendor_context: str = None) -> str:
    """Build the full extraction prompt with optional vendor context."""
    parts = [EXTRACTION_PROMPT]
    if vendor_context:
        parts.append(f"\nKnown vendor profile (use to improve accuracy):\n{vendor_context}\n")
    parts.append(f"\nInvoice text to extract from:\n\n{ocr_text}")
    return "\n".join(parts)


def build_correction_prompt(original_extraction: dict, corrections: dict) -> str:
    """Prompt used when a human corrects extracted fields — for vendor learning."""
    import json
    return f"""
A human reviewer corrected the following invoice extraction.

Original extraction:
{json.dumps(original_extraction, indent=2)}

Human corrections:
{json.dumps(corrections, indent=2)}

Summarize in JSON what layout or format hints should be stored for this vendor to improve future extractions.
Return ONLY valid JSON with a "layout_hints" key.
"""
