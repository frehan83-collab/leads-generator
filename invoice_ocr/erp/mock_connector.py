"""Mock ERP connector for testing and development."""

import logging
from datetime import datetime

from .base_connector import ERPConnector

logger = logging.getLogger(__name__)


class MockERPConnector(ERPConnector):
    """Simulates an ERP integration. Logs all calls and returns dummy data."""

    def post_invoice(self, invoice_data: dict) -> dict:
        logger.info(
            "MockERP: posting invoice %s from %s (total: %s %s)",
            invoice_data.get("invoice_number"),
            invoice_data.get("vendor_name"),
            invoice_data.get("total_amount"),
            invoice_data.get("currency"),
        )
        return {
            "success": True,
            "erp_id": f"ERP-{invoice_data.get('invoice_number', 'UNKNOWN')}",
            "posted_at": datetime.utcnow().isoformat(),
            "message": "Invoice posted to mock ERP successfully",
        }

    def get_gl_accounts(self) -> list[dict]:
        return [
            {"code": "6000", "name": "Operating Expenses"},
            {"code": "6100", "name": "Office Supplies"},
            {"code": "6200", "name": "Travel & Entertainment"},
            {"code": "6300", "name": "Professional Services"},
            {"code": "6400", "name": "Rent"},
            {"code": "6500", "name": "Utilities"},
            {"code": "7000", "name": "Cost of Goods Sold"},
        ]

    def match_purchase_order(self, po_number: str) -> dict:
        if not po_number:
            return {}
        return {
            "po_number": po_number,
            "status": "open",
            "vendor": "Mock Vendor",
            "amount": 10000.00,
            "currency": "NOK",
            "remaining": 10000.00,
        }
