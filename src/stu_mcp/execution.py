"""Public execution scope without automatic device or network identification."""
from __future__ import annotations

import os
import re

# An optional human-chosen label, never an OS hostname, account, path or address.
_INSTANCE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z", re.ASCII)


def execution_context() -> dict:
    """Describe where work runs, without claiming a successful network check.

    Resolve the label on each report so cached network evidence cannot retain a
    previous display name. Renaming does not change that evidence or its age.
    """
    configured = os.environ.get("STU_MCP_INSTANCE_NAME", "").strip()
    name = configured if _INSTANCE_NAME.fullmatch(configured) else "unnamed"
    return {
        "scope": "mcp_host",
        "instance_name": name,
        "client_network_checked": False,
        "school_route_automatic": False,
        "physical_location_detection": False,
        "client_connection_check": "transport_handshake_only",
    }
