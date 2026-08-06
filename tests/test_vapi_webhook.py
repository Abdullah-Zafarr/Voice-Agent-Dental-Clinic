import asyncio
from datetime import date

from api.index import execute_dental_tool, infer_api_request_tool, normalize_email, parse_requested_date, prototype_slots


def test_parse_requested_date_supports_weekdays():
    assert parse_requested_date("Tuesday", date(2026, 8, 3)) == date(2026, 8, 4)


def test_prototype_slots_excludes_weekends():
    assert prototype_slots("2026-08-08", "2026-08-09") == []


def test_pricing_tool_returns_a_result_without_crm():
    result = asyncio.run(execute_dental_tool("get_dental_pricing", {"service_name": "cleaning"}))
    assert result == {"success": True, "message": "Standard cleaning is $150 to $220."}


def test_direct_api_request_tool_is_inferred_from_its_schema():
    assert infer_api_request_tool({"date_from": "tomorrow"}) == "check_availability"
    assert infer_api_request_tool({"slot_time": "2026-08-10 09:00 AM"}) == "book_appointment"


def test_normalize_email_converts_spoken_email_phrases():
    assert normalize_email("Jane at the rate Gmail dot com") == "jane@gmail.com"
