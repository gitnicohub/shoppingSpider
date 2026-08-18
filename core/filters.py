from __future__ import annotations

from core.config_loader import Target
from scrapers.base import ListingResult


def passes_filters(result: ListingResult, target: Target) -> bool:
    if target.max_price is not None and result.price > target.max_price:
        return False

    title_lower = result.title.lower()

    for keyword in target.keywords_include:
        if keyword.lower() not in title_lower:
            return False

    for keyword in target.keywords_exclude:
        if keyword.lower() in title_lower:
            return False

    if target.seller and (result.seller or "").lower() != target.seller.lower():
        return False

    if target.condition and (result.condition or "").lower() != target.condition.lower():
        return False

    return True
