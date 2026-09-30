from datetime import datetime, timedelta

from app import perception, safety

NOW = datetime(2026, 9, 30, 19, 40)


def test_cooked_ambient_is_four_hours():
    win = safety.safe_window("cooked", "ambient", NOW.replace(hour=18, minute=0), NOW)
    assert win["safe_until"] == NOW.replace(hour=22, minute=0)
    assert win["urgency"] == "HIGH"


def test_expired_when_inside_serve_buffer():
    win = safety.safe_window("cooked", "ambient", NOW - timedelta(hours=3, minutes=30), NOW)
    assert win["urgency"] == "EXPIRED"


def test_chilled_lasts_longer():
    win = safety.safe_window("cooked", "chilled", NOW.replace(hour=18), NOW)
    assert win["urgency"] == "LOW"


def test_nut_free_recipient_blocked():
    food = {"allergens": ["tree_nuts"], "halal": True, "storage": "ambient"}
    result = safety.dietary_check(food, {"id": "r2", "name": "Care home", "excludes_allergens": ["tree_nuts"]})
    assert not result["ok"]


def test_parse_english_note():
    facts = perception.parse_note("50 chicken biryani, has cashews, cooked at 6", NOW)
    assert facts["portions"] == 50
    assert facts["dish"] == "chicken biryani"
    assert facts["allergens"] == ["tree_nuts"]
    assert facts["prepared_at"].startswith("2026-09-30T18:00")


def test_parse_missing_time():
    facts = perception.parse_note("30 trays of pasta with cheese", NOW)
    assert facts["missing"] == ["prepared_at"]
    assert "dairy" in facts["allergens"] and "gluten" in facts["allergens"]
