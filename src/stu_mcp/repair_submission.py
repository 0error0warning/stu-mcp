"""Compatibility imports for the former monolithic submission module."""
from .features.repair.adapter import capture_form as capture_form
from .features.repair.parser import normalize_body as normalize_body
from .features.repair.schema import (
    BUSINESS_FIELDS as BUSINESS_FIELDS,
)
from .features.repair.schema import (
    LABELS as LABELS,
)
from .features.repair.schema import (
    RAW_TO_DRAFT as RAW_TO_DRAFT,
)
from .features.repair.schema import (
    SYSTEM_FIELDS as SYSTEM_FIELDS,
)
from .features.repair.service import REVIEW_SECONDS as REVIEW_SECONDS
from .features.repair.service import check_review as check_review
from .features.repair.service import review_result as review_result
from .features.repair.submission import (
    SubmissionGate as SubmissionGate,
)
from .features.repair.submission import (
    check_submission_result as check_submission_result,
)
from .features.repair.submission import (
    forward_submission as forward_submission,
)
from .features.repair.submission import (
    submit_reviewed_form as submit_reviewed_form,
)
