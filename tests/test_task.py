from datetime import date
import pytest
from pydantic import ValidationError
from jetson_browser.models import ExtractedTask, resolve_date


@pytest.mark.parametrize('text,expected', [
    ('明天', date(2026, 11, 3)),
    ('下周五', date(2026, 11, 13)),
    ('本周五', date(2026, 11, 6)),
    ('下下周日', date(2026, 11, 22)),
    ('2026-12-01', date(2026, 12, 1)),
    ('2026年12月1日', date(2026, 12, 1)),
])
def test_date_resolves_from_shanghai_calendar(text, expected):
    assert resolve_date(text, date(2026, 11, 2)) == expected


def test_next_week_crosses_year():
    assert resolve_date('下周五', date(2026, 12, 31)) == date(2027, 1, 8)


@pytest.mark.parametrize('text', ['周五', '11月5日', '2026-02-30', '2026-01-01'])
def test_ambiguous_invalid_or_past_dates_require_clarification(text):
    with pytest.raises(ValueError):
        resolve_date(text, date(2026, 11, 2))


def test_page_cannot_inject_model_endpoint_into_task():
    with pytest.raises(ValidationError):
        ExtractedTask(origin='深圳', model_endpoint='https://untrusted.example')
