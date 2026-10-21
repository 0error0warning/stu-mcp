"""Compatibility exports for the layered anonymous Huyou feature."""
# Keep the shared module object for existing callers patching huyou.time.sleep/monotonic.
import time as time

from .features.huyou.adapter import sign_params as sign_params
from .features.huyou.cache import (
    empty_discussion as empty_discussion,
)
from .features.huyou.cache import (
    merge_discussion as merge_discussion,
)
from .features.huyou.cache import (
    merge_post as merge_post,
)
from .features.huyou.cache import (
    post_preview as post_preview,
)
from .features.huyou.cache import (
    searchable_text as searchable_text,
)
from .features.huyou.parser import (
    comment_record as comment_record,
)
from .features.huyou.parser import (
    cursor as cursor,
)
from .features.huyou.parser import (
    feed_id as feed_id,
)
from .features.huyou.parser import (
    image_urls as image_urls,
)
from .features.huyou.parser import (
    integer as integer,
)
from .features.huyou.parser import (
    numeric_id as numeric_id,
)
from .features.huyou.parser import (
    page_rows as page_rows,
)
from .features.huyou.parser import (
    param_string as param_string,
)
from .features.huyou.parser import (
    post_record as post_record,
)
from .features.huyou.parser import (
    published as published,
)
from .features.huyou.parser import (
    search_plan as search_plan,
)
from .features.huyou.parser import (
    text as text,
)
from .features.huyou.schema import (
    API_BASE as API_BASE,
)
from .features.huyou.schema import (
    API_PATHS as API_PATHS,
)
from .features.huyou.schema import (
    APP_VERSION as APP_VERSION,
)
from .features.huyou.schema import (
    DEFAULT_CIRCLE as DEFAULT_CIRCLE,
)
from .features.huyou.schema import (
    PUBLIC_SIGNING_CONSTANT as PUBLIC_SIGNING_CONSTANT,
)
from .features.huyou.schema import (
    STOP_CODES as STOP_CODES,
)
from .features.huyou.schema import (
    WEB_BASE as WEB_BASE,
)
from .features.huyou.service import HuyouClient as HuyouClient
