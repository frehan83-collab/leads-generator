from .base_connector import ERPConnector
from .mock_connector import MockERPConnector

# Default connector — swap for real ERP in production
active_connector: ERPConnector = MockERPConnector()

__all__ = ["ERPConnector", "MockERPConnector", "active_connector"]
