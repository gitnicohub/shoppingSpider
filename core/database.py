from __future__ import annotations

import enum
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import DateTime, Float, Integer, String, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from scrapers.base import ListingResult


class Base(DeclarativeBase):
    pass


class Listing(Base):
    __tablename__ = "listings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_id: Mapped[str] = mapped_column(String, index=True)
    adapter: Mapped[str] = mapped_column(String)
    external_id: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(String)
    url: Mapped[str] = mapped_column(String)
    seller: Mapped[str | None] = mapped_column(String, nullable=True)
    condition: Mapped[str | None] = mapped_column(String, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime)
    first_price: Mapped[float] = mapped_column(Float)
    last_price: Mapped[float] = mapped_column(Float)
    last_notified_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    notified_count: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint("target_id", "adapter", "external_id", name="uq_listing_identity"),
    )


class NotificationAction(str, enum.Enum):
    NONE = "none"
    NEW = "new"
    PRICE_DROP = "price_drop"


def compute_external_id(adapter: str, product_key: str) -> str:
    raw = f"{adapter}:{product_key}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def init_db(db_path: str) -> sessionmaker:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)


def process_listing(
    session: Session,
    target_id: str,
    adapter: str,
    result: ListingResult,
    renotify_drop_pct: float,
) -> tuple[NotificationAction, Listing]:
    external_id = compute_external_id(adapter, result.product_key)
    now = datetime.now(timezone.utc)

    listing = (
        session.query(Listing)
        .filter_by(target_id=target_id, adapter=adapter, external_id=external_id)
        .one_or_none()
    )

    if listing is None:
        listing = Listing(
            target_id=target_id,
            adapter=adapter,
            external_id=external_id,
            title=result.title,
            url=result.url,
            seller=result.seller,
            condition=result.condition,
            first_seen_at=now,
            last_seen_at=now,
            first_price=result.price,
            last_price=result.price,
            last_notified_price=None,
            notified_count=0,
        )
        session.add(listing)
    else:
        listing.last_seen_at = now
        listing.last_price = result.price
        listing.url = result.url

    if listing.last_notified_price is None:
        action = NotificationAction.NEW
    elif listing.last_notified_price <= 0:
        # Percentage drop is undefined when notified at zero or negative price.
        # Treat as no re-notification opportunity (e.g., free/giveaway items).
        action = NotificationAction.NONE
    else:
        drop_pct = (listing.last_notified_price - result.price) / listing.last_notified_price
        action = NotificationAction.PRICE_DROP if drop_pct >= renotify_drop_pct else NotificationAction.NONE

    session.commit()
    return action, listing


def mark_notified(session: Session, listing: Listing, price: float) -> None:
    listing.last_notified_price = price
    listing.notified_count += 1
    session.commit()
