"""Food-safety and dietary rules. Plain code, never the model.

The hours below are demo values based on common time-and-temperature guidance
(for example, cooked food should not sit at room temperature for more than about
4 hours in total). Validate them against Dubai Municipality food-safety guidance
before real use.
"""
from datetime import datetime, timedelta

from . import config

# Hours from preparation until the food must be served, by category and storage.
SAFE_HOURS = {
    "cooked": {"ambient": 4, "hot_held": 6, "chilled": 48, "frozen": 720},
    "raw_protein": {"ambient": 2, "hot_held": 2, "chilled": 24, "frozen": 720},
    "produce": {"ambient": 48, "hot_held": 4, "chilled": 96, "frozen": 720},
    "bakery": {"ambient": 24, "hot_held": 6, "chilled": 48, "frozen": 720},
    "dairy": {"ambient": 2, "hot_held": 2, "chilled": 48, "frozen": 720},
    "packaged": {"ambient": 72, "hot_held": 6, "chilled": 120, "frozen": 720},
}

ALLERGENS = {"tree_nuts", "peanuts", "dairy", "eggs", "gluten", "shellfish", "fish", "sesame", "soy"}


def safe_window(category: str, storage: str, prepared_at: datetime, now: datetime) -> dict:
    """Return the serve-by time, how long is left, and an urgency level."""
    category = category if category in SAFE_HOURS else "cooked"
    storage = storage if storage in SAFE_HOURS[category] else "ambient"
    hours = SAFE_HOURS[category][storage]
    safe_until = prepared_at + timedelta(hours=hours)
    minutes_left = (safe_until - now) / timedelta(minutes=1)
    rescuable_minutes = minutes_left - config.SERVE_BUFFER_MIN
    if rescuable_minutes <= 0:
        urgency = "EXPIRED"
    elif minutes_left < 3 * 60:
        urgency = "HIGH"
    elif minutes_left < 12 * 60:
        urgency = "MEDIUM"
    else:
        urgency = "LOW"
    return {
        "category": category,
        "storage": storage,
        "rule_hours": hours,
        "safe_until": safe_until,
        "minutes_left": round(minutes_left),
        "deliver_by": safe_until - timedelta(minutes=config.SERVE_BUFFER_MIN),
        "urgency": urgency,
    }


def dietary_check(food: dict, recipient: dict) -> dict:
    """Check one surplus item against one recipient's rules."""
    reasons = []
    blocked = set(food.get("allergens", [])) & set(recipient.get("excludes_allergens", []))
    if blocked:
        reasons.append(f"contains {', '.join(sorted(blocked))}, which {recipient['name']} does not accept")
    if recipient.get("halal_required", True) and not food.get("halal", True):
        reasons.append("not halal")
    if recipient.get("vegetarian_only") and not food.get("vegetarian", False):
        reasons.append("not vegetarian")
    if food.get("storage") == "chilled" and not recipient.get("has_fridge", True):
        reasons.append("needs refrigeration the recipient does not have")
    return {"recipient_id": recipient["id"], "ok": not reasons, "reasons": reasons}
