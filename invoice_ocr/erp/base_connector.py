"""Abstract ERP connector interface."""

from abc import ABC, abstractmethod


class ERPConnector(ABC):
    """Generic interface for posting invoices to any ERP system."""

    @abstractmethod
    def post_invoice(self, invoice_data: dict) -> dict:
        """Post an approved invoice to the ERP. Returns the ERP response."""

    @abstractmethod
    def get_gl_accounts(self) -> list[dict]:
        """Return available GL accounts from the ERP."""

    @abstractmethod
    def match_purchase_order(self, po_number: str) -> dict:
        """Look up a PO in the ERP by number. Returns PO details or empty dict."""
