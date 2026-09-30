"""Message templates in English and Arabic (Urdu for drivers).

Messages are templated in code rather than written by the model, so wording on
safety-critical facts (allergens, serve-by time) is always exact.
"""

ALLERGEN_NAMES = {
    "tree_nuts": ("tree nuts", "مكسرات"),
    "peanuts": ("peanuts", "فول سوداني"),
    "dairy": ("dairy", "ألبان"),
    "eggs": ("eggs", "بيض"),
    "gluten": ("gluten", "غلوتين"),
    "shellfish": ("shellfish", "مأكولات بحرية"),
    "fish": ("fish", "سمك"),
    "sesame": ("sesame", "سمسم"),
    "soy": ("soy", "صويا"),
}


def allergens_text(allergens: list[str], lang: str) -> str:
    if not allergens:
        return "no listed allergens" if lang == "en" else "لا توجد مسببات حساسية مذكورة"
    idx = 0 if lang == "en" else 1
    sep = ", " if lang == "en" else "، "
    return sep.join(ALLERGEN_NAMES.get(a, (a, a))[idx] for a in allergens)


def donor_ack(f: dict) -> dict:
    return {
        "en": f"Got it: {f['portions']} portions of {f['dish']}. Contains {allergens_text(f['allergens'], 'en')}. "
        f"Safe to serve until {f['safe_until']}. Finding homes for it now.",
        "ar": f"تم الاستلام: {f['portions']} وجبة {f['dish_ar']}. تحتوي على {allergens_text(f['allergens'], 'ar')}. "
        f"صالحة للتقديم حتى {f['safe_until']}. نبحث الآن عن جهات تستفيد منها.",
    }


def donor_expired(f: dict) -> dict:
    return {
        "en": f"This food is past its safe window (serve by {f['safe_until']}), so we can't send it anywhere tonight. "
        "Please discard it safely.",
        "ar": f"انتهت فترة الأمان لهذا الطعام (التقديم قبل {f['safe_until']})، لذلك لا يمكن إرساله الليلة. "
        "يُرجى التخلص منه بشكل آمن.",
    }


def donor_question(question_en: str, question_ar: str) -> dict:
    return {"en": question_en, "ar": question_ar}


def offer(o: dict) -> dict:
    return {
        "en": f"{o['portions']} portions of {o['dish']} from {o['donor']}. Contains {allergens_text(o['allergens'], 'en')}. "
        f"Halal. Arrives about {o['eta']}. Serve before {o['safe_until']}.",
        "ar": f"{o['portions']} وجبة {o['dish_ar']} من {o['donor']}. تحتوي على {allergens_text(o['allergens'], 'ar')}. "
        f"حلال. الوصول حوالي {o['eta']}. يجب التقديم قبل {o['safe_until']}.",
    }


def recipient_confirmed(c: dict) -> dict:
    return {
        "en": f"Confirmed: {c['driver']} arrives about {c['eta']} with {c['portions']} portions. Serve before {c['safe_until']}.",
        "ar": f"تم التأكيد: {c['driver']} يصل حوالي {c['eta']} ومعه {c['portions']} وجبة. يجب التقديم قبل {c['safe_until']}.",
    }


def donor_dispatched(d: dict) -> dict:
    return {
        "en": f"{d['driver']} collects at {d['pickup_eta']}. Going to {d['count']} places: {d['stops_en']}.",
        "ar": f"{d['driver']} يستلم الساعة {d['pickup_eta']}. التوزيع على {d['count']} جهات: {d['stops_ar']}.",
    }


def driver_job(j: dict) -> dict:
    return {
        "en": f"New pickup at {j['donor']} at {j['pickup_eta']}: {j['portions']} portions, keep in the cold box. "
        f"Then: {j['stops_en']}.",
        "ar": f"استلام جديد من {j['donor']} الساعة {j['pickup_eta']}: {j['portions']} وجبة، تُحفظ في الصندوق المبرد. "
        f"ثم: {j['stops_ar']}.",
        "ur": f"نیا پک اپ: {j['donor']}، وقت {j['pickup_eta']}۔ {j['portions']} کھانے، ٹھنڈے باکس میں رکھیں۔ "
        f"پھر: {j['stops_en']}۔",
    }


def unsafe_on_arrival(safe_until: str) -> dict:
    return {
        "en": f"Arrived after the safe window (serve by {safe_until}). Do not serve this food.",
        "ar": f"وصل الطعام بعد انتهاء فترة الأمان (التقديم قبل {safe_until}). يُرجى عدم تقديمه.",
    }


def impact_note(i: dict) -> dict:
    if i.get("kg") is None:
        return {
            "en": f"All handovers confirmed: {i['meals']} meals received by {i['recipients']} organisations.",
            "ar": f"تم تأكيد كل عمليات التسليم: استلمت {i['recipients']} جهات {i['meals']} وجبة.",
        }
    return {
        "en": f"All handovers confirmed: {i['meals']} meals received, about {i['kg']} kg of food and {i['co2e_kg']} kg CO2e.",
        "ar": f"تم تأكيد كل عمليات التسليم: {i['meals']} وجبة، حوالي {i['kg']} كغ من الطعام و{i['co2e_kg']} كغ من مكافئ ثاني أكسيد الكربون.",
    }
