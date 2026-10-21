"""Shared conservative page-completeness check for course APIs."""

def complete_list(payload: dict, size: int, capacity: int | None = None) -> bool:
    """A full page or explicit remaining results is never a replacement snapshot."""
    if capacity is not None and size >= capacity:
        return False
    for key in ("has_more", "hasMore", "has_next", "hasNext", "has_next_page", "next", "nextPage"):
        if payload.get(key):
            return False
    for key in ("total", "total_count", "totalCount", "count"):
        value = payload.get(key)
        if value is not None:
            try:
                if int(value) > size or int(value) < 0:
                    return False
            except (TypeError, ValueError):
                return False
    for key in ("total_pages", "totalPages", "page_count", "pageCount"):
        if payload.get(key, 1) != 1:
            return False
    pagination = payload.get("pagination")
    return not isinstance(pagination, dict) or complete_list(pagination, size)
