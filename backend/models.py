from datetime import datetime, timezone
from sqlalchemy import (
    BigInteger, DateTime, ForeignKey, Identity, Integer,
    Numeric, String, Text, UniqueConstraint
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    source: Mapped[str] = mapped_column(String(30))
    source_post_id: Mapped[str] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(Text)
    content: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        UniqueConstraint("source", "source_post_id"),
    )


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"))
    category: Mapped[str | None] = mapped_column(String(50))
    brand: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(255))
    price_vnd: Mapped[int | None] = mapped_column(Numeric(15, 0))
    condition: Mapped[str | None] = mapped_column(String(50))


class Classification(Base):
    __tablename__ = "classifications"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    post_id: Mapped[int] = mapped_column(
        ForeignKey("posts.id"), unique=True
    )
    seller_type: Mapped[str] = mapped_column(String(30))
    confidence: Mapped[float | None] = mapped_column(Numeric(5, 4))
    lead_score: Mapped[int | None] = mapped_column(Integer)
    classified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
