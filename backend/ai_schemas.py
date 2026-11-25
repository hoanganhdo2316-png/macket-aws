from typing import Literal

from pydantic import BaseModel, Field


class Stage1Classification(BaseModel):
    post_type: Literal["selling", "buying", "other"]
    seller_type: Literal["individual", "seller", "unknown"]
    confidence: float = Field(ge=0, le=1)
    reason: str


class Specification(BaseModel):
    name: str
    value: str


class Product(BaseModel):
    category: str | None
    brand: str | None
    model: str | None
    specifications: list[Specification]
    price_vnd: int | None
    condition: Literal["new", "used", "unknown"]


class Stage2Extraction(BaseModel):
    products: list[Product]
    location: str | None
