from datetime import date, datetime, timedelta
from enum import Enum
import re
from zoneinfo import ZoneInfo
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Status(str, Enum):
    RUNNING = 'RUNNING'
    SUCCEEDED = 'SUCCEEDED'
    NO_RESULTS = 'NO_RESULTS'
    NEEDS_USER = 'NEEDS_USER'
    BLOCKED = 'BLOCKED'
    FAILED = 'FAILED'
    CANCELLED = 'CANCELLED'


class ExtractedTask(BaseModel):
    model_config = ConfigDict(extra='forbid')
    origin: str | None = None
    destination: str | None = None
    date_text: str | None = None
    adults: int = Field(default=1, ge=1, le=9)
    cabin: Literal['economy', 'premium_economy', 'business', 'first', 'unknown'] = 'economy'
    trip_type: Literal['one_way', 'round_trip', 'multi_city', 'unknown'] = 'one_way'
    direct_only: bool = False
    direct_preferred: bool = False
    price_preferred: bool = False
    budget: float | None = Field(default=None, gt=0)
    currency: str | None = None


class FlightTask(ExtractedTask):
    departure_date: date
    original_request: str
    created_at: str
    site: str = 'trip'
    open_details: bool = True


def resolve_date(expression: str, today: date | None = None) -> date:
    today = today or datetime.now(ZoneInfo('Asia/Shanghai')).date()
    s = expression.strip()
    offsets = {'今天': 0, '明天': 1, '后天': 2, '大后天': 3}
    if s in offsets:
        result = today + timedelta(days=offsets[s])
    elif m := re.fullmatch(r'(本|这|下|下下)周([一二三四五六日天])', s):
        weekday = '一二三四五六日'.index(m[2].replace('天', '日'))
        weeks = {'本': 0, '这': 0, '下': 1, '下下': 2}[m[1]]
        result = today - timedelta(days=today.weekday()) + timedelta(weeks=weeks, days=weekday)
    elif re.fullmatch(r'\d{4}-\d{1,2}-\d{1,2}', s):
        result = date(*map(int, s.split('-')))
    elif m := re.fullmatch(r'(\d{4})年(\d{1,2})月(\d{1,2})[日号]?', s):
        result = date(*map(int, m.groups()))
    else:
        raise ValueError(f'Date "{expression}" needs clarification; provide YYYY-MM-DD or a supported relative date')
    if result < today:
        raise ValueError(f'Departure date {result} is in the past')
    return result
