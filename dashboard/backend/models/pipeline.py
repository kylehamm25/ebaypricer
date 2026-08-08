from pydantic import BaseModel
from typing import Optional, Literal
from datetime import datetime


class PipelineStatus(BaseModel):
    state: Literal["idle", "running"]
    pid: Optional[int] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    exit_code: Optional[int] = None
    last_run_at: Optional[str] = None


class RunHistory(BaseModel):
    timestamp: str
    status: str
    duration_sec: Optional[float] = None
