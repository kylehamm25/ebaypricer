from pydantic import BaseModel
from typing import Optional


class Campaign(BaseModel):
    campaign_id: str
    campaign_name: str
    campaign_status: str
    funding_model: Optional[str]


class AdItem(BaseModel):
    listing_id: str
    bid_percentage: float
