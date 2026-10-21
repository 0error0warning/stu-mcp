"""Stable charging imports; provider contracts and workflows live in features/charging."""
from __future__ import annotations

import threading

from .charging_devices import DEVICES as DEVICES
from .charging_devices import Device
from .features.charging.adapter import ChargingClient as _ChargingClient
from .features.charging.models import PublicConfig as PublicConfig
from .features.charging.parser import ScriptSources as ScriptSources
from .features.charging.parser import parse_ports as parse_ports
from .features.charging.parser import sign_params as sign_params
from .features.charging.parser import timestamp as timestamp
from .features.charging.schema import AFTER_TYPES as AFTER_TYPES
from .features.charging.schema import API_PATHS as API_PATHS
from .features.charging.schema import BASE as BASE
from .features.charging.schema import BEFORE_TYPES as BEFORE_TYPES
from .features.charging.schema import STATE_LABELS as STATE_LABELS
from .features.charging.schema import STOP_CODES as STOP_CODES
from .features.charging.service import ChargingService as _ChargingService

_CONFIG_LOCK = threading.Lock()
_CONFIG: PublicConfig | None = None


class _CompatibleConfigCache:
    """Keep the former cache reset/injection point without a reverse feature import."""
    lock = _CONFIG_LOCK

    @property
    def current(self):
        return _CONFIG

    @current.setter
    def current(self, value):
        global _CONFIG
        _CONFIG = value


class ChargingClient(_ChargingClient):
    def __init__(self, *, transport=None):
        super().__init__(transport=transport, config_cache=_CompatibleConfigCache())


class ChargingService(_ChargingService):
    def __init__(self, store, *, devices: tuple[Device, ...] | None = None, clock=None):
        super().__init__(store, devices=DEVICES if devices is None else devices, clock=clock,
                         client_factory=lambda: ChargingClient())
