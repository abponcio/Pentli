"""Turn a kitchen's photo and note (English or Arabic) into structured facts.

AGENT_MODE=bedrock: Claude on Amazon Bedrock reads the photo and the note.
AGENT_MODE=mock: a keyword parser reads the note only (the photo is stored but not read).
"""
import base64
import json
import re
from datetime import datetime, timedelta

from . import clock, config

ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
ARABIC_NUMBER_WORDS = {
    "مية": 100, "مائة": 100, "مئة": 100, "ستين": 60, "ستون": 60, "خمسين": 50, "خمسون": 50,
    "أربعين": 40, "اربعين": 40, "أربعون": 40, "ثلاثين": 30, "ثلاثون": 30, "عشرين": 20, "عشرون": 20,
    "خمسة عشر": 15, "خمستعش": 15, "عشرة": 10, "عشر": 10,
}
DISHES = [  # (keywords, english name, arabic name, category)
    (("biryani", "برياني", "بریانی"), "biryani", "برياني", "cooked"),
    (("machboos", "مجبوس", "كبسة", "kabsa"), "machboos", "مجبوس", "cooked"),
    (("curry", "كاري"), "curry", "كاري", "cooked"),
    (("pasta", "باستا", "معكرونة"), "pasta", "باستا", "cooked"),
    (("rice", "رز", "أرز", "ارز"), "rice", "أرز", "cooked"),
    (("salad", "سلطة", "vegetable", "خضار", "fruit", "فواكه"), "salad and vegetables", "سلطة وخضار", "produce"),
    (("bread", "خبز", "bakery", "مخبوزات", "sandwich", "ساندويتش"), "bread and sandwiches", "خبز وساندويتشات", "bakery"),
    (("meal kit", "box", "بوكس", "صندوق"), "meal kits", "صناديق وجبات", "packaged"),
]
ALLERGEN_WORDS = {
    "tree_nuts": ("cashew", "nut", "almond", "pistachio", "walnut", "كاجو", "مكسرات", "لوز", "فستق", "جوز"),
    "peanuts": ("peanut", "فول سوداني"),
    "dairy": ("milk", "cream", "cheese", "yogurt", "yoghurt", "butter", "paneer", "ghee", "حليب", "قشطة", "جبن", "لبن", "زبدة", "سمن"),
    "eggs": ("egg", "بيض"),
    "gluten": ("bread", "wheat", "pasta", "flour", "خبز", "قمح", "طحين"),
    "shellfish": ("shrimp", "prawn", "crab", "روبيان", "جمبري"),
    "fish": ("fish", "سمك"),
    "sesame": ("sesame", "tahini", "سمسم", "طحينة"),
}
STORAGE_WORDS = {
    "chilled": ("chilled", "fridge", "cold room", "chiller", "مبرد", "ثلاجة", "براد"),
    "hot_held": ("hot", "warmer", "bain", "ساخن", "حار"),
    "frozen": ("frozen", "freezer", "مجمد", "فريزر"),
    "ambient": ("room temp", "room temperature", "ambient", "درجة حرارة الغرفة", "خارج الثلاجة"),
}
MEAT_WORDS = ("chicken", "meat", "beef", "lamb", "mutton", "fish", "shrimp", "دجاج", "لحم", "غنم", "سمك")
NOT_HALAL_WORDS = ("pork", "bacon", "ham", "alcohol", "wine", "خنزير", "كحول")


def is_arabic(text: str) -> bool:
    return bool(re.search(r"[؀-ۿ]", text or ""))


def _resolve_time(hour: int, minute: int, meridiem: str | None, now: datetime) -> datetime:
    if meridiem:
        hour = hour % 12 + (12 if meridiem.lower().startswith("p") else 0)
        candidates = [now.replace(hour=hour, minute=minute, second=0, microsecond=0)]
    else:
        candidates = [now.replace(hour=h % 24, minute=minute, second=0, microsecond=0) for h in {hour, hour + 12} if h < 24]
    past = [c for c in candidates if c <= now]
    return max(past) if past else min(candidates) - timedelta(days=1)


def parse_note(text: str, now: datetime | None = None) -> dict:
    """Keyword parser used in mock mode and as a fallback when the model call fails."""
    now = now or clock.now()
    raw = (text or "").translate(ARABIC_DIGITS)
    low = raw.lower()

    prepared_at, time_span = None, None
    m = None
    for pattern in (
        r"(?:\bat|@)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b",
        r"\b(?:cooked|made|prepared)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b",
        r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b",
        r"(?:الساعة|الساعه)\s*(\d{1,2})(?::(\d{2}))?",
    ):
        m = re.search(pattern, low)
        if m:
            break
    if m:
        groups = m.groups()
        meridiem = groups[2] if len(groups) > 2 else None
        prepared_at = _resolve_time(int(groups[0]), int(groups[1] or 0), meridiem, now)
        time_span = m.span()

    rest = low if not time_span else low[: time_span[0]] + " " + low[time_span[1]:]
    portions = None
    n = re.search(r"\b(\d{1,4})\b", rest)
    if n:
        portions = int(n.group(1))
    else:
        for word, value in ARABIC_NUMBER_WORDS.items():
            if word in rest:
                portions = value
                break

    dish, dish_ar, category = "mixed meals", "وجبات متنوعة", "cooked"
    for keys, name, name_ar, cat in DISHES:
        if any(k in low for k in keys):
            dish, dish_ar, category = name, name_ar, cat
            break
    has_chicken = any(k in low for k in ("chicken", "دجاج"))
    if has_chicken and dish in ("biryani", "machboos", "curry", "rice"):
        dish, dish_ar = f"chicken {dish}", f"{dish_ar} دجاج"

    storage = "ambient"
    for kind, keys in STORAGE_WORDS.items():
        if any(k in low for k in keys):
            storage = kind
            break

    allergens = sorted(a for a, keys in ALLERGEN_WORDS.items() if any(k in low for k in keys))
    missing = []
    if portions is None:
        missing.append("portions")
    if prepared_at is None:
        missing.append("prepared_at")
    return {
        "dish": dish,
        "dish_ar": dish_ar,
        "portions": portions,
        "category": category,
        "storage": storage,
        "prepared_at": prepared_at.isoformat() if prepared_at else None,
        "allergens": allergens,
        "halal": not any(k in low for k in NOT_HALAL_WORDS),
        "vegetarian": not any(k in low for k in MEAT_WORDS),
        "language": "ar" if is_arabic(text) else "en",
        "missing": missing,
        "source": "keyword parser",
    }


PROMPT = """You are the intake step of a food-rescue service in Dubai. A commercial kitchen sent a photo of surplus food
and a short note (English or Arabic). Extract the facts. Use the note for anything the photo cannot show
(allergens, time cooked, storage). The current Dubai time is {now}.

Note: <<<{note}>>>

Reply with only a JSON object with these keys:
dish (short English name), dish_ar (Arabic name), portions (integer or null if unknown),
category (one of cooked, raw_protein, produce, bakery, dairy, packaged),
storage (one of ambient, hot_held, chilled, frozen; ambient if the note does not say),
prepared_time (HH:MM 24-hour Dubai time, or null if unknown),
allergens (list from tree_nuts, peanuts, dairy, eggs, gluten, shellfish, fish, sesame, soy; include ones clearly visible or stated),
halal (true unless pork or alcohol is visible or stated), vegetarian (boolean),
notes (one short sentence on anything that looks unsafe or unclear, or empty)."""


def classify_with_bedrock(note: str, photo: bytes | None, photo_format: str = "jpeg") -> dict:
    import boto3

    now = clock.now()
    client = boto3.client("bedrock-runtime", region_name=config.BEDROCK_REGION)
    content = []
    if photo:
        content.append({"image": {"format": photo_format, "source": {"bytes": photo}}})
    content.append({"text": PROMPT.format(now=now.strftime("%Y-%m-%d %H:%M"), note=note or "(no note)")})
    resp = client.converse(
        modelId=config.BEDROCK_MODEL_ID,
        messages=[{"role": "user", "content": content}],
        inferenceConfig={"maxTokens": 1024},
    )
    text = "".join(block.get("text", "") for block in resp["output"]["message"]["content"])
    data = json.loads(text[text.find("{"): text.rfind("}") + 1])

    prepared_at = None
    if data.get("prepared_time"):
        hour, minute = (int(x) for x in data["prepared_time"].split(":"))
        prepared_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if prepared_at > now:
            prepared_at -= timedelta(days=1)
    missing = [k for k, v in (("portions", data.get("portions")), ("prepared_at", prepared_at)) if not v]
    return {
        "dish": data.get("dish") or "mixed meals",
        "dish_ar": data.get("dish_ar") or "وجبات متنوعة",
        "portions": data.get("portions"),
        "category": data.get("category") or "cooked",
        "storage": data.get("storage") or "ambient",
        "prepared_at": prepared_at.isoformat() if prepared_at else None,
        "allergens": sorted(set(data.get("allergens") or [])),
        "halal": bool(data.get("halal", True)),
        "vegetarian": bool(data.get("vegetarian", False)),
        "language": "ar" if is_arabic(note) else "en",
        "missing": missing,
        "notes": data.get("notes", ""),
        "source": f"Claude on Bedrock ({config.BEDROCK_MODEL_ID})",
    }


def classify(note: str, photo_b64: str | None = None, photo_format: str = "jpeg") -> dict:
    if config.AGENT_MODE != "bedrock":
        facts = parse_note(note)
        if photo_b64:
            facts["notes"] = "Photo stored; mock mode reads the note only."
        return facts
    try:
        return classify_with_bedrock(note, base64.b64decode(photo_b64) if photo_b64 else None, photo_format)
    except Exception as exc:
        facts = parse_note(note)
        facts["notes"] = f"Model call failed ({type(exc).__name__}); used the keyword parser."
        return facts
