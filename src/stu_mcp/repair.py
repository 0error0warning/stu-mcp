"""Compatibility imports; implementation lives in features.repair."""
from .features.repair import RepairDrafts as RepairDrafts
from .features.repair.adapter import (
    direct_preflight as direct_preflight,
)
from .features.repair.adapter import (
    field_plan as field_plan,
)
from .features.repair.adapter import (
    fill_form as fill_form,
)
from .features.repair.adapter import (
    read_form as read_form,
)
from .features.repair.adapter import (
    request_allowed as request_allowed,
)
from .features.repair.adapter import (
    select_calendar as select_calendar,
)
from .features.repair.models import ACTIVE as ACTIVE
from .features.repair.models import campus_today as campus_today
from .features.repair.models import validate_fields as validate_fields
from .features.repair.schema import (
    BUILDINGS as BUILDINGS,
)
from .features.repair.schema import (
    CAPABILITY as CAPABILITY,
)
from .features.repair.schema import (
    DIRECT_BROWSER_ARGS as DIRECT_BROWSER_ARGS,
)
from .features.repair.schema import (
    FIELDS as FIELDS,
)
from .features.repair.schema import (
    OPTIONAL as OPTIONAL,
)
from .features.repair.schema import (
    POSTBACK_FIELDS as POSTBACK_FIELDS,
)
from .features.repair.schema import (
    REPAIR_FORM as REPAIR_FORM,
)
from .features.repair.schema import (
    REPAIR_HOME as REPAIR_HOME,
)
from .features.repair.schema import (
    ROOT as ROOT,
)
from .features.repair.schema import (
    SELECT_FIELDS as SELECT_FIELDS,
)
from .features.repair.schema import (
    TEXT_FIELDS as TEXT_FIELDS,
)
from .features.repair.schema import (
    TIME_EVENTS as TIME_EVENTS,
)
from .features.repair.schema import (
    VERIFIED_ON as VERIFIED_ON,
)
