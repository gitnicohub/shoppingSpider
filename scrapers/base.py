from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from core.config_loader import Target


@dataclass
class ListingResult:
    product_key: str
    title: str
    url: str
    price: float
    seller: str | None = None
    condition: str | None = None


class BaseScraper(ABC):
    def __init__(self, antibot_config) -> None:
        self.antibot_config = antibot_config

    @abstractmethod
    async def search(self, target: Target) -> list[ListingResult]:
        raise NotImplementedError
