from datetime import date
from types import SimpleNamespace

import pytest

from jetson_browser.llm import local_url
from jetson_browser.locations import location
from jetson_browser.models import FlightTask
from jetson_browser.trip import Blocked, Trip, nonstop_status


@pytest.mark.parametrize('url', ['https://api.example.com', 'http://127.0.0.1.evil.test', 'file:///tmp/model'])
def test_external_model_endpoints_rejected(url):
    with pytest.raises(ValueError):
        local_url(url)


@pytest.mark.parametrize('label', ['Pay now', 'Confirm booking', 'Submit order', 'Book now', '提交订单'])
def test_transaction_actions_rejected(label):
    with pytest.raises(Blocked):
        Trip.transaction_guard({'label': label})


def test_city_and_specific_airport_are_distinct():
    city = location('上海')
    assert city.matches_selected('Shanghai · All airports')
    assert not city.matches_selected('Shanghai Pudong Airport PVG')
    assert not city.matches_selected('Shanghai · All airports Beijing · All airports')
    assert not city.matches_airport('CAN Guangzhou Baiyun International Airport')
    assert city.matches_airport('PVG Shanghai Pudong International Airport T2')


def test_unverified_candidate_cannot_pass_date_or_route_filters():
    task = FlightTask(origin='深圳', destination='上海', date_text='2026-11-13',
                      departure_date=date(2026, 11, 13), original_request='test', created_at='test', direct_only=True)
    trip = Trip(task)
    base = {'route_verified': True, 'departure_date': '2026-11-13', 'nonstop': True, 'price': 100}
    assert trip.eligible([base]) == [base]
    for changes in [{'route_verified': False}, {'departure_date': '2026-11-14'}, {'nonstop': None}, {'nonstop': False}]:
        assert not trip.eligible([{**base, **changes}])


def test_results_need_submitted_query_proof():
    trip = Trip(FlightTask(origin='深圳', destination='上海', date_text='2026-11-13',
                          departure_date=date(2026, 11, 13), original_request='test', created_at='test'))
    obs = SimpleNamespace(url='https://www.trip.com/?ddate=2026-11-13', text='1 adult Economy')
    assert not trip.verify_result_query(obs)


def test_completed_fields_cannot_be_undone_while_setting_date():
    trip = Trip(FlightTask(origin='深圳', destination='上海', date_text='2026-11-13',
                          departure_date=date(2026, 11, 13), original_request='test', created_at='test'))
    actions = [
        {'id': 'swap', 'label': 'Switch departure airport or city and arrival airport or city', 'kind': 'click'},
        {'id': 'remove', 'label': 'Remove Shanghai', 'kind': 'click', 'dom_label': 'Remove', 'field_label': 'Arrival airport or city'},
        {'id': 'date', 'label': 'Choose date', 'role': 'textbox', 'kind': 'click'},
        {'id': 'search', 'label': 'Search', 'kind': 'click'},
    ]
    checks = dict(origin=True, destination=True, one_way=True, date=False, passengers_cabin=True, nonstop_filter=True)
    allowed, _ = trip.allowed_form_actions(SimpleNamespace(data={'actions': actions}), checks)
    assert [a['id'] for a in allowed] == ['date']


def test_city_request_cannot_select_airport_or_point_of_interest():
    trip = Trip(FlightTask(origin='深圳', destination='杭州', date_text='2026-11-13',
                          departure_date=date(2026, 11, 13), original_request='test', created_at='test'))
    base = {'kind': 'click', 'field_label': 'Arrival airport or city'}
    actions = [dict(base, id='city', label='Hangzhou · All airports China', role='button'),
               dict(base, id='airport', label='HGH Hangzhou Xiaoshan International Airport', role='listitem'),
               dict(base, id='poi', label='Hangzhou Orient Culture Park Zhejiang, China', role='button')]
    checks = dict(origin=True, destination=False, one_way=True, date=False, passengers_cabin=True, nonstop_filter=True)
    allowed, _ = trip.allowed_form_actions(SimpleNamespace(data={'actions': actions}), checks)
    assert [a['id'] for a in allowed] == ['city']


@pytest.mark.parametrize('summary,text,expected', [
    ('This is a nonstop flight', '', True),
    ('The flight includes a layover of Shanghai', '20h 45m in Shanghai', False),
    ('', '1 stop', False),
    ('', 'Schedule unavailable', None),
])
def test_explicit_layover_is_not_reported_as_unknown_or_nonstop(summary, text, expected):
    assert nonstop_status(summary, text) is expected
