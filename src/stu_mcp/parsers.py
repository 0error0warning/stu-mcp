"""Compatibility imports for feature parsers and shared pure helpers."""
from __future__ import annotations

from .features.jw.parser import jw_authenticated as jw_authenticated
from .features.jw.parser import jw_exam_semester as jw_exam_semester
from .features.jw.parser import parse_jw as parse_jw
from .features.jw.schema import JW_COLUMNS as JW_COLUMNS
from .features.jw.schema import JW_SCHEMA_VERSION as JW_SCHEMA_VERSION
from .features.mystu.parser import current_courses as current_courses
from .features.mystu.parser import parse_assignment as parse_assignment
from .features.mystu.parser import parse_elc as parse_elc
from .features.mystu.parser import payload_records as payload_records
from .features.notices.parser import parse_links as parse_links
from .features.notices.parser import parse_oa as parse_oa
from .features.notices.parser import parse_oa_article as parse_oa_article
from .features.notices.parser import parse_public as parse_public
from .parsing import CST as CST
from .parsing import clean as clean
from .parsing import is_login as is_login
from .parsing import item_id as item_id
from .parsing import parse_date as parse_date
from .parsing import published as published
from .parsing import stamp as stamp
from .parsing import text_body as text_body
