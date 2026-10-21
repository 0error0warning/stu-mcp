"""Compatibility imports for receipt parsing and acquisition."""
from .features.repair.parser import (
    clean as clean,
)
from .features.repair.parser import (
    detail_link as detail_link,
)
from .features.repair.parser import (
    expected_fields as expected_fields,
)
from .features.repair.parser import (
    list_rows as list_rows,
)
from .features.repair.parser import (
    match_detail as match_detail,
)
from .features.repair.parser import (
    on_page as on_page,
)
from .features.repair.parser import (
    school_time as school_time,
)
from .features.repair.receipt import ReceiptVerifier as ReceiptVerifier
from .features.repair.schema import DETAIL_SCRIPT as DETAIL_SCRIPT
from .features.repair.schema import LIST_SCRIPT as LIST_SCRIPT
from .features.repair.schema import LIST_URL as LIST_URL
from .features.repair.schema import ROOT as ROOT
from .features.repair.schema import STATUSES as STATUSES
