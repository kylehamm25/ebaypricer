from pydantic import BaseModel
from typing import Optional


class SoldListing(BaseModel):
    item_id: str
    card_query: Optional[str]
    title: str
    price: float
    currency: str
    condition: Optional[str]
    listing_type: str
    sold_date: str
    url: Optional[str]
    pulled_at: Optional[str]


class SoldSummary(BaseModel):
    total_count: int
    total_revenue: float
    avg_price: float
    median_price: float
    min_price: float
    max_price: float


class SoldTrend(BaseModel):
    date: str
    count: int
    revenue: float


class SoldByCard(BaseModel):
    card_query: str
    count: int
    avg_price: float
    total_revenue: float
    min_price: float
    max_price: float


class PaginatedSoldResponse(BaseModel):
    items: list[SoldListing]
    total: int
    page: int
    per_page: int
