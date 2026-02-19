"""Tests for the invoice OCR extraction pipeline."""

import json
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── Sample extraction fixtures ────────────────────────────────────────────────

SAMPLE_EXTRACTION = {
    "vendor_name": "Acme AS",
    "vendor_address": "Storgata 1, 0155 Oslo",
    "vendor_email": "invoice@acme.no",
    "vendor_phone": "+47 22 00 00 00",
    "invoice_number": "INV-2024-001",
    "invoice_date": "2024-01-15",
    "due_date": "2024-02-14",
    "currency": "NOK",
    "subtotal": 10000.00,
    "tax_amount": 2500.00,
    "tax_rate": 25.0,
    "total_amount": 12500.00,
    "po_number": "PO-9999",
    "payment_terms": "Net 30",
    "bank_details": {"iban": "NO93 8601 1117 947", "swift": "DNBANOKKXXX"},
    "line_items": [
        {"description": "Consulting services Jan", "quantity": 10, "unit_price": 1000.00, "line_total": 10000.00, "gl_account": "6300", "tax_code": "MVA25"},
    ],
    "confidence_score": 0.96,
    "extraction_notes": None,
}

DUPLICATE_EXTRACTION = dict(SAMPLE_EXTRACTION)  # same invoice_number + vendor + amount


# ── Validator tests ────────────────────────────────────────────────────────────

class TestInvoiceValidator:
    def _make_db(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from invoice_ocr.models.base import Base
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        return sessionmaker(bind=engine)()

    def test_valid_invoice_passes(self):
        from invoice_ocr.validators import validate_invoice
        db = self._make_db()
        result = validate_invoice(SAMPLE_EXTRACTION, db)
        assert result.is_valid
        assert not result.errors
        assert not result.needs_review  # confidence 0.96 > 0.85

    def test_math_error_detected(self):
        from invoice_ocr.validators import validate_invoice
        bad = dict(SAMPLE_EXTRACTION, total_amount=99999.00)
        db = self._make_db()
        result = validate_invoice(bad, db)
        assert not result.is_valid
        assert any("does not match total" in e for e in result.errors)

    def test_line_item_sum_mismatch(self):
        from invoice_ocr.validators import validate_invoice
        bad = dict(SAMPLE_EXTRACTION, subtotal=5000.00)
        db = self._make_db()
        result = validate_invoice(bad, db)
        assert not result.is_valid

    def test_low_confidence_needs_review(self):
        from invoice_ocr.validators import validate_invoice
        low_conf = dict(SAMPLE_EXTRACTION, confidence_score=0.70)
        db = self._make_db()
        result = validate_invoice(low_conf, db)
        assert result.needs_review

    def test_duplicate_detection(self):
        from invoice_ocr.validators import validate_invoice
        from invoice_ocr.models.invoice import Invoice
        import hashlib
        db = self._make_db()
        # Insert a fake existing invoice with the same hash
        raw = f"{SAMPLE_EXTRACTION['invoice_number']}|{SAMPLE_EXTRACTION['vendor_name']}|{SAMPLE_EXTRACTION['total_amount']}"
        h = hashlib.sha256(raw.encode()).hexdigest()
        inv = Invoice(
            original_filename="test.pdf",
            file_path="/tmp/test.pdf",
            file_format="pdf",
            invoice_number=SAMPLE_EXTRACTION["invoice_number"],
            vendor_name=SAMPLE_EXTRACTION["vendor_name"],
            total_amount=SAMPLE_EXTRACTION["total_amount"],
            content_hash=h,
        )
        db.add(inv)
        db.commit()
        result = validate_invoice(DUPLICATE_EXTRACTION, db)
        assert result.is_duplicate


# ── Extractor tests ────────────────────────────────────────────────────────────

class TestExtractors:
    def test_pdf_extractor_can_handle(self):
        from invoice_ocr.extractors.pdf_extractor import PDFExtractor
        ext = PDFExtractor()
        assert ext.can_handle("invoice.pdf")
        assert not ext.can_handle("invoice.jpg")

    def test_image_extractor_can_handle(self):
        from invoice_ocr.extractors.image_extractor import ImageExtractor
        ext = ImageExtractor()
        assert ext.can_handle("scan.jpg")
        assert ext.can_handle("receipt.png")
        assert not ext.can_handle("data.csv")

    def test_xml_extractor_can_handle(self):
        from invoice_ocr.extractors.xml_extractor import XMLExtractor
        ext = XMLExtractor()
        assert ext.can_handle("invoice.xml")
        assert ext.can_handle("invoice.edi")
        assert not ext.can_handle("invoice.pdf")

    def test_csv_extractor_can_handle(self):
        from invoice_ocr.extractors.csv_extractor import CSVExtractor
        ext = CSVExtractor()
        assert ext.can_handle("invoices.csv")
        assert ext.can_handle("invoices.xlsx")
        assert not ext.can_handle("invoice.pdf")

    def test_extractor_registry_pdf(self):
        from invoice_ocr.extractors import get_extractor
        from invoice_ocr.extractors.pdf_extractor import PDFExtractor
        assert isinstance(get_extractor("invoice.pdf"), PDFExtractor)

    def test_extractor_registry_unknown_raises(self):
        from invoice_ocr.extractors import get_extractor
        with pytest.raises(ValueError):
            get_extractor("invoice.docx")

    def test_xml_extractor_parses_simple_xml(self, tmp_path):
        from invoice_ocr.extractors.xml_extractor import XMLExtractor
        xml_file = tmp_path / "invoice.xml"
        xml_file.write_text("""<?xml version="1.0"?>
<Invoice>
  <VendorName>Test Vendor</VendorName>
  <InvoiceNumber>INV-001</InvoiceNumber>
  <TotalAmount>5000.00</TotalAmount>
</Invoice>""")
        result = XMLExtractor().extract(str(xml_file))
        assert "Test Vendor" in result.text
        assert "INV-001" in result.text
        assert result.error is None

    def test_csv_extractor_parses_csv(self, tmp_path):
        from invoice_ocr.extractors.csv_extractor import CSVExtractor
        csv_file = tmp_path / "invoice.csv"
        csv_file.write_text("vendor,invoice_number,total\nAcme,INV-001,5000\n")
        result = CSVExtractor().extract(str(csv_file))
        assert "Acme" in result.text
        assert result.error is None


# ── Claude client tests (mocked) ───────────────────────────────────────────────

class TestClaudeClient:
    @pytest.mark.asyncio
    async def test_extract_from_text_returns_dict(self):
        from invoice_ocr.ai.claude_client import ClaudeExtractionClient
        client = ClaudeExtractionClient()

        mock_message = MagicMock()
        mock_message.content = [MagicMock(text=json.dumps(SAMPLE_EXTRACTION))]

        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_stream.__aexit__ = AsyncMock(return_value=False)
        mock_stream.get_final_message = AsyncMock(return_value=mock_message)

        with patch.object(client._client.messages, "stream", return_value=mock_stream):
            result = await client.extract_from_text("Sample invoice text")

        assert result["vendor_name"] == "Acme AS"
        assert result["total_amount"] == 12500.00

    @pytest.mark.asyncio
    async def test_handles_malformed_json(self):
        from invoice_ocr.ai.claude_client import ClaudeExtractionClient
        client = ClaudeExtractionClient()

        mock_message = MagicMock()
        mock_message.content = [MagicMock(text="NOT VALID JSON")]

        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_stream.__aexit__ = AsyncMock(return_value=False)
        mock_stream.get_final_message = AsyncMock(return_value=mock_message)

        with patch.object(client._client.messages, "stream", return_value=mock_stream):
            result = await client.extract_from_text("bad text")

        assert result["confidence_score"] == 0.0
        assert "extraction_notes" in result


# ── ERP connector tests ────────────────────────────────────────────────────────

class TestMockERP:
    def test_post_invoice(self):
        from invoice_ocr.erp.mock_connector import MockERPConnector
        conn = MockERPConnector()
        result = conn.post_invoice(SAMPLE_EXTRACTION)
        assert result["success"] is True
        assert "erp_id" in result

    def test_get_gl_accounts(self):
        from invoice_ocr.erp.mock_connector import MockERPConnector
        conn = MockERPConnector()
        accounts = conn.get_gl_accounts()
        assert len(accounts) > 0
        assert "code" in accounts[0]

    def test_match_po(self):
        from invoice_ocr.erp.mock_connector import MockERPConnector
        conn = MockERPConnector()
        result = conn.match_purchase_order("PO-9999")
        assert result["po_number"] == "PO-9999"


# ── Vendor learning tests ──────────────────────────────────────────────────────

class TestVendorLearning:
    def _make_db(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from invoice_ocr.models.base import Base
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        return sessionmaker(bind=engine)()

    def test_creates_profile_on_first_invoice(self):
        from invoice_ocr.ai.vendor_learning import get_or_create_profile
        db = self._make_db()
        profile = get_or_create_profile(db, "Acme AS", "invoice@acme.no")
        assert profile.id is not None
        assert profile.vendor_name == "Acme AS"

    def test_returns_existing_profile(self):
        from invoice_ocr.ai.vendor_learning import get_or_create_profile
        db = self._make_db()
        p1 = get_or_create_profile(db, "Acme AS", "invoice@acme.no")
        p2 = get_or_create_profile(db, "Acme AS Different Name", "invoice@acme.no")
        assert p1.id == p2.id  # matched by domain

    def test_updates_running_average(self):
        from invoice_ocr.ai.vendor_learning import get_or_create_profile, update_profile_after_extraction
        db = self._make_db()
        profile = get_or_create_profile(db, "Acme AS", "invoice@acme.no")
        update_profile_after_extraction(db, profile, SAMPLE_EXTRACTION, 0.90)
        update_profile_after_extraction(db, profile, SAMPLE_EXTRACTION, 0.80)
        assert profile.invoice_count == 2
        assert abs(profile.avg_confidence - 0.85) < 0.01
