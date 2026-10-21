"""Composition root for the isolated dorm repair feature."""
from functools import partial

from .http_adapter import open_http
from .models import SessionFactory
from .schema import CAPABILITY
from .service import RepairService

__all__ = ["CAPABILITY", "RepairDrafts"]

class RepairDrafts(RepairService):
    """Existing API, with an injectable school session for offline workflow tests."""
    def __init__(self, adapter_factory: SessionFactory | None = None, *, vault=None):
        super().__init__(adapter_factory or partial(open_http, vault=vault))
