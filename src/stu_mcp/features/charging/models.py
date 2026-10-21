"""In-memory public client configuration; never include values in repr or results."""
from dataclasses import dataclass, field


@dataclass(repr=False)
class PublicConfig:
    app_id: str = field(repr=False)
    secret: str = field(repr=False)
    loaded_at: float = field(repr=False)
