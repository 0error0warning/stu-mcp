"""Composition root for the isolated dorm repair feature."""
from .adapter import open_browser
from .models import SessionFactory
from .schema import CAPABILITY
from .service import RepairService

__all__ = ["CAPABILITY", "RepairDrafts"]

class RepairDrafts(RepairService):
    """Existing API, with an injectable school session for offline workflow tests."""
    def __init__(self, adapter_factory: SessionFactory = open_browser):
        super().__init__(adapter_factory)
