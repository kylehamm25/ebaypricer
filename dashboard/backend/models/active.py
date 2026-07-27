from pydantic import BaseModel
from typing import Optional


class ActiveListing(BaseModel):
    item_id: str
    title: str
    card: Optional[str]
    condition: Optional[str]
    sku: Optional[str]
    price: Optional[float]
    shipping_charge: Optional[float]
    ad_rate: Optional[str]
    watchers: Optional[int]
    days_listed: Optional[int]
    start_date: Optional[str]
    quantity: Optional[int]
    estimated_fees: Optional[float]
    estimated_net: Optional[float]
    recent_sold_avg: Optional[float]
    price_vs_sold_avg: Optional[float]
    recent_sold_count: Optional[int]
    last_checked: Optional[str]
    active_avg_top5: Optional[float]
    price_accuracy: Optional[float]


class ActiveSummary(BaseModel):
    total_listings: int
    total_value: float
    avg_days_listed: float
    avg_watchers: float
    avg_price: float


class ConditionDist(BaseModel):
    condition: str
    count: int


class DaysBucket(BaseModel):
    bucket: str
    count: int


class PaginatedActiveResponse(BaseModel):
    items: list[ActiveListing]
    total: int
    page: int
    per_page: int
