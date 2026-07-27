from pydantic import BaseModel
from typing import Optional


class PriceSnapshot(BaseModel):
    card_query: str
    snapshot_date: str
    sample_size: int
    avg_price: float
    median_price: float
    min_price: float
    max_price: float
    std_dev: float
    weighted_avg: float


class ActivePriceSnapshot(BaseModel):
    card_query: str
    snapshot_date: str
    sample_size: int
    avg_price: float
    min_price: float
    max_price: float


class PriceComparison(BaseModel):
    card_query: str
    sold_weighted_avg: Optional[float]
    sold_sample: Optional[int]
    active_avg: Optional[float]
    active_sample: Optional[int]
    spread: Optional[float]


class CardPriceDetail(BaseModel):
    card_query: str
    price_snapshots: list[PriceSnapshot]
    active_snapshots: list[ActivePriceSnapshot]
    recent_sold: list
