"""The agent's tools. Each one is plain Python that returns JSON-safe data.

The model (or the mock planner) decides which tool to call next; these functions
own every fact and every safety rule. Each call writes a line to the ops trace.
"""
import threading
import time
from datetime import datetime, timedelta

from . import clock, config, events, geo, messages, notify, perception, photos, safety
from .store import store

TOOL_NAMES = [
    "classify_surplus", "ask_donor", "get_safe_window", "find_recipients", "check_dietary",
    "validate_allocation", "send_offers", "find_drivers", "plan_route", "dispatch_and_notify",
]


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _rescue(rescue_id: str) -> dict:
    rescue = store.get("rescue", rescue_id)
    if not rescue:
        raise ValueError(f"unknown rescue {rescue_id}")
    return rescue


def _pos(obj: dict) -> tuple[float, float]:
    return obj["lat"], obj["lng"]


def _count_tool(rescue_id: str) -> None:
    rescue = _rescue(rescue_id)
    store.update("rescue", rescue_id, tool_calls=rescue.get("tool_calls", 0) + 1)


def _ops_update(rescue_id: str) -> None:
    events.emit("rescue", rescue_id, ["ops"], rescue=public_rescue(_rescue(rescue_id)))


def public_rescue(rescue: dict) -> dict:
    return dict(rescue)


# 1 ---------------------------------------------------------------------------
def classify_surplus(rescue_id: str) -> dict:
    """Read the kitchen's photo and note: dish, portions, allergens, halal, when it was cooked, storage."""
    _count_tool(rescue_id)
    rescue = _rescue(rescue_id)
    note = " ".join([rescue.get("note", "")] + rescue.get("replies", []))
    photo = photos.get(rescue_id)
    facts = perception.classify(note, photo["b64"] if photo else None, photo["format"] if photo else "jpeg")
    store.update("rescue", rescue_id, facts=facts, status="intake")
    summary = (
        f"{facts['portions'] or '?'} × {facts['dish']}, allergens: {', '.join(facts['allergens']) or 'none'}, "
        f"{'halal' if facts['halal'] else 'NOT halal'}, {facts['storage']}, "
        f"cooked {clock.fmt(_dt(facts['prepared_at'])) if facts['prepared_at'] else '?'}"
    )
    events.trace(rescue_id, "classify_surplus", "AI", summary, {"source": facts["source"], "missing": facts["missing"]})
    _ops_update(rescue_id)
    return facts


# 2 ---------------------------------------------------------------------------
def ask_donor(rescue_id: str, question_en: str, question_ar: str, wait_seconds: float = 90) -> dict:
    """Ask the kitchen one short question and wait for the reply. Returns the reply text, or timed_out."""
    _count_tool(rescue_id)
    rescue = _rescue(rescue_id)
    replies_before = len(rescue.get("replies", []))
    store.update("rescue", rescue_id, status="waiting_donor")
    notify.send(f"kitchen:{rescue['donor_id']}", messages.donor_question(question_en, question_ar), rescue_id, sender="plenty")
    events.trace(rescue_id, "ask_donor", "AI", f"Asked the kitchen: {question_en}")
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        replies = _rescue(rescue_id).get("replies", [])
        if len(replies) > replies_before:
            store.update("rescue", rescue_id, status="intake")
            return {"reply": replies[-1]}
        time.sleep(0.5)
    return {"timed_out": True}


# 3 ---------------------------------------------------------------------------
def get_safe_window(rescue_id: str) -> dict:
    """Compute the serve-by time from the food-safety rule table. Code decides; the model cannot change it."""
    _count_tool(rescue_id)
    rescue = _rescue(rescue_id)
    facts = rescue["facts"]
    if not facts.get("prepared_at"):
        return {"error": "prepared_at unknown; ask the donor when the food was cooked"}
    win = safety.safe_window(facts["category"], facts["storage"], _dt(facts["prepared_at"]), clock.now())
    out = {
        "safe_until": win["safe_until"].isoformat(),
        "deliver_by": win["deliver_by"].isoformat(),
        "minutes_left": win["minutes_left"],
        "urgency": win["urgency"],
        "rule": f"{win['category']} kept {win['storage']}: serve within {win['rule_hours']} h of cooking",
    }
    store.update("rescue", rescue_id, safety=out)
    donor_key = f"kitchen:{rescue['donor_id']}"
    fmt = {**facts, "safe_until": clock.fmt(win["safe_until"])}
    if win["urgency"] == "EXPIRED":
        store.update("rescue", rescue_id, status="expired")
        notify.send(donor_key, messages.donor_expired(fmt), rescue_id, sender="plenty")
        events.trace(rescue_id, "get_safe_window", "CODE", f"Past safe window ({clock.fmt(win['safe_until'])}). Rescue stopped.", out, "blocked")
    else:
        notify.send(donor_key, messages.donor_ack(fmt), rescue_id, sender="plenty", card={
            "type": "surplus", "portions": facts["portions"], "dish": facts["dish"], "dish_ar": facts["dish_ar"],
            "allergens": facts["allergens"], "safe_until": clock.fmt(win["safe_until"])})
        events.trace(
            rescue_id, "get_safe_window", "CODE",
            f"Serve by {clock.fmt(win['safe_until'])}, deliver by {clock.fmt(win['deliver_by'])}. Urgency {win['urgency']}.", out,
        )
    _ops_update(rescue_id)
    return out


# 4 ---------------------------------------------------------------------------
def _is_open(recipient: dict, at: datetime) -> bool:
    hhmm = at.strftime("%H:%M")
    return recipient["open_from"] <= hhmm <= recipient["open_to"]


def find_recipients(rescue_id: str) -> dict:
    """List recipients that are open now, within driving range, and can be reached before the deliver-by time."""
    _count_tool(rescue_id)
    rescue = _rescue(rescue_id)
    donor = store.get("donor", rescue["donor_id"])
    deliver_by = _dt(rescue["safety"]["deliver_by"])
    now = clock.now()
    declined = set(rescue.get("declined", []))
    accepted = rescue.get("accepted", {})
    eligible, excluded = [], []
    for r in store.list("recipient"):
        leg = geo.drive(_pos(donor), _pos(r))
        row = {
            "id": r["id"], "name": r["name"], "type": r["type"], "priority": r["priority"],
            "need_tonight": r["need_tonight"] - accepted.get(r["id"], 0),
            "drive_minutes": leg["minutes"], "km": leg["km"], "excludes_allergens": r["excludes_allergens"],
        }
        if r["id"] in declined:
            excluded.append({**row, "reason": "declined tonight's offer"})
        elif not _is_open(r, now):
            excluded.append({**row, "reason": f"closed (open {r['open_from']} to {r['open_to']})"})
        elif leg["minutes"] > config.MAX_DRIVE_MIN:
            excluded.append({**row, "reason": f"{leg['minutes']:.0f} min away, over the {config.MAX_DRIVE_MIN:.0f} min limit"})
        elif now + timedelta(minutes=leg["minutes"] + 20) > deliver_by:
            excluded.append({**row, "reason": "cannot be reached before the deliver-by time"})
        elif row["need_tonight"] <= 0:
            excluded.append({**row, "reason": "need already covered"})
        else:
            eligible.append(row)
    eligible.sort(key=lambda x: (x["priority"], x["drive_minutes"]))
    store.update("rescue", rescue_id, candidates=eligible, status="matching")
    events.trace(
        rescue_id, "find_recipients", "CODE",
        f"{len(eligible)} in range: " + ", ".join(f"{e['name']} ({e['need_tonight']})" for e in eligible)
        + (f". Excluded: " + "; ".join(f"{x['name']}: {x['reason']}" for x in excluded) if excluded else ""),
        {"eligible": eligible, "excluded": excluded},
    )
    return {"eligible": eligible, "excluded": excluded}


# 5 ---------------------------------------------------------------------------
def check_dietary(rescue_id: str, recipient_ids: list[str]) -> dict:
    """Check the food against each recipient's allergen, halal and storage rules."""
    _count_tool(rescue_id)
    rescue = _rescue(rescue_id)
    facts = rescue["facts"]
    results = {}
    for rid in recipient_ids:
        recipient = store.get("recipient", rid)
        if recipient:
            results[rid] = safety.dietary_check(facts, recipient)
    dietary = {**rescue.get("dietary", {}), **results}
    store.update("rescue", rescue_id, dietary=dietary)
    blocked = [f"{store.get('recipient', rid)['name']}: {'; '.join(r['reasons'])}" for rid, r in results.items() if not r["ok"]]
    passed = [store.get("recipient", rid)["name"] for rid, r in results.items() if r["ok"]]
    events.trace(
        rescue_id, "check_dietary", "CODE",
        f"Pass: {', '.join(passed) or 'none'}." + (f" Blocked: {' | '.join(blocked)}." if blocked else ""),
        {"results": results}, "ok" if not blocked else "warn",
    )
    return {"results": results}


# 6 ---------------------------------------------------------------------------
def _allocation_violations(rescue: dict, allocation: dict[str, int]) -> list[str]:
    facts = rescue["facts"]
    accepted = rescue.get("accepted", {})
    remaining = (facts.get("portions") or 0) - sum(accepted.values())
    violations = []
    if sum(allocation.values()) > remaining:
        violations.append(f"allocates {sum(allocation.values())} portions but only {remaining} are unplaced")
    candidates = {c["id"]: c for c in rescue.get("candidates", [])}
    for rid, portions in allocation.items():
        if portions <= 0:
            violations.append(f"{rid}: portions must be positive")
        if rid not in candidates:
            violations.append(f"{rid}: not an eligible recipient from find_recipients")
            continue
        if not rescue.get("dietary", {}).get(rid, {}).get("ok"):
            violations.append(f"{rid}: has not passed check_dietary")
        if portions > candidates[rid]["need_tonight"]:
            violations.append(f"{rid}: {portions} is more than their need of {candidates[rid]['need_tonight']}")
        if rid in rescue.get("declined", []):
            violations.append(f"{rid}: already declined")
    return violations


def validate_allocation(rescue_id: str, allocation: dict[str, int]) -> dict:
    """Check a proposed split of portions across recipients (recipient id -> portions) before offering it."""
    _count_tool(rescue_id)
    rescue = _rescue(rescue_id)
    violations = _allocation_violations(rescue, allocation)
    names = {r["id"]: r["name"] for r in store.list("recipient")}
    text = ", ".join(f"{p} to {names.get(rid, rid)}" for rid, p in allocation.items())
    if violations:
        events.trace(rescue_id, "validate_allocation", "CODE", f"Rejected split ({text}): {'; '.join(violations)}", {"allocation": allocation}, "blocked")
        return {"ok": False, "violations": violations}
    store.update("rescue", rescue_id, allocation=allocation)
    events.trace(rescue_id, "validate_allocation", "CODE", f"Split OK: {text}", {"allocation": allocation})
    return {"ok": True}


# 7 ---------------------------------------------------------------------------
def _simulate_response(offer_id: str, decision: str, delay: float) -> None:
    def respond():
        offer = store.get("offer", offer_id)
        if offer and offer["status"] == "pending":
            respond_to_offer(offer_id, decision, simulated=True)
    threading.Timer(delay, respond).start()


def respond_to_offer(offer_id: str, decision: str, simulated: bool = False) -> dict:
    offer = store.get("offer", offer_id)
    if not offer or offer["status"] != "pending":
        return {"ok": False, "reason": "offer is no longer open"}
    status = "accepted" if decision == "accept" else "declined"
    offer = store.update("offer", offer_id, status=status, responded_at=clock.now().isoformat(), simulated=simulated)
    events.emit("offer", offer["rescue_id"], ["ops", f"recipient:{offer['recipient_id']}"], offer=offer)
    return {"ok": True, "offer": offer}


def send_offers(rescue_id: str, allocation: dict[str, int]) -> dict:
    """Send each recipient an offer with Accept and Decline, then wait for their answers (declines and
    no-answers come back so you can re-plan)."""
    _count_tool(rescue_id)
    rescue = _rescue(rescue_id)
    violations = _allocation_violations(rescue, allocation)
    if violations:
        events.trace(rescue_id, "send_offers", "CODE", f"Refused to send: {'; '.join(violations)}", {}, "blocked")
        return {"ok": False, "violations": violations}
    facts, donor = rescue["facts"], store.get("donor", rescue["donor_id"])
    safe_until = clock.fmt(_dt(rescue["safety"]["safe_until"]))
    offer_ids = []
    for rid, portions in allocation.items():
        recipient = store.get("recipient", rid)
        eta = clock.now() + timedelta(minutes=geo.drive(_pos(donor), _pos(recipient))["minutes"] + 20)
        offer = {
            "id": f"{rescue_id}-{rid}-{len(rescue.get('offers', [])) + len(offer_ids) + 1}",
            "rescue_id": rescue_id, "recipient_id": rid, "portions": portions, "status": "pending",
            "dish": facts["dish"], "dish_ar": facts["dish_ar"], "allergens": facts["allergens"],
            "eta": clock.fmt(eta), "safe_until": safe_until, "created_at": clock.now().isoformat(),
            "expires_at_ts": time.time() + config.OFFER_TIMEOUT_SECONDS,
        }
        store.put("offer", offer)
        offer_ids.append(offer["id"])
        texts = messages.offer({**offer, "donor": donor["name"]})
        notify.send(f"recipient:{rid}", texts, rescue_id, sender="plenty", offer=offer)
        events.emit("offer", rescue_id, ["ops"], offer=offer)
        if recipient.get("responder") == "auto_accept":
            _simulate_response(offer["id"], "accept", config.SIM_RESPONSE_SECONDS)
        elif recipient.get("responder") == "auto_decline":
            _simulate_response(offer["id"], "decline", config.SIM_RESPONSE_SECONDS)
    store.update("rescue", rescue_id, offers=rescue.get("offers", []) + offer_ids, status="offering")
    names = {r["id"]: r["name"] for r in store.list("recipient")}
    events.trace(rescue_id, "send_offers", "CODE", "Offers sent: " + ", ".join(f"{p} to {names[r]}" for r, p in allocation.items()) + ". Waiting for answers.")
    _ops_update(rescue_id)

    deadline = time.time() + config.OFFER_TIMEOUT_SECONDS
    while time.time() < deadline:
        if all(store.get("offer", oid)["status"] != "pending" for oid in offer_ids):
            break
        time.sleep(0.4)

    accepted, declined, timed_out = {}, [], []
    for oid in offer_ids:
        offer = store.get("offer", oid)
        if offer["status"] == "pending":
            offer = store.update("offer", oid, status="expired")
            events.emit("offer", rescue_id, ["ops", f"recipient:{offer['recipient_id']}"], offer=offer)
            timed_out.append(offer["recipient_id"])
        elif offer["status"] == "accepted":
            accepted[offer["recipient_id"]] = offer["portions"]
        else:
            declined.append(offer["recipient_id"])
    rescue = _rescue(rescue_id)
    all_accepted = dict(rescue.get("accepted", {}))
    for rid, p in accepted.items():
        all_accepted[rid] = all_accepted.get(rid, 0) + p
    store.update(
        "rescue", rescue_id, accepted=all_accepted,
        declined=sorted(set(rescue.get("declined", []) + declined + timed_out)),
    )
    unplaced = (rescue["facts"]["portions"] or 0) - sum(all_accepted.values())
    events.trace(
        rescue_id, "send_offers", "CODE",
        "Answers: " + ", ".join([f"{names[r]} accepted {p}" for r, p in accepted.items()]
                                + [f"{names[r]} declined" for r in declined]
                                + [f"{names[r]} did not answer" for r in timed_out])
        + f". {unplaced} portions still unplaced.",
        {"accepted": accepted, "declined": declined, "timed_out": timed_out},
        "ok" if not (declined or timed_out) else "warn",
    )
    _ops_update(rescue_id)
    return {"accepted": accepted, "declined": declined, "timed_out": timed_out, "unplaced_portions": unplaced,
            "all_accepted_so_far": all_accepted}


# 8 ---------------------------------------------------------------------------
def find_drivers(rescue_id: str) -> dict:
    """Rank drivers: the donor's own returning vans first, then volunteers; nearest first."""
    _count_tool(rescue_id)
    rescue = _rescue(rescue_id)
    donor = store.get("donor", rescue["donor_id"])
    portions = sum(rescue.get("accepted", {}).values())
    ranked = []
    for d in store.list("driver"):
        leg = geo.drive(_pos(d), _pos(donor))
        ranked.append({
            "id": d["id"], "name": d["name"], "driver": d["driver"], "kind": d["kind"], "status": d["status"],
            "minutes_to_pickup": leg["minutes"], "cold_box": d["cold_box"],
            "fits_load": d["capacity_portions"] >= portions,
        })
    ranked.sort(key=lambda d: (not d["fits_load"], d["kind"] != "returning_van", not d["cold_box"], d["minutes_to_pickup"]))
    events.trace(
        rescue_id, "find_drivers", "CODE",
        " | ".join(f"{d['name']} ({d['driver']}), {d['minutes_to_pickup']:.0f} min, {'cold box' if d['cold_box'] else 'no cold box'}" for d in ranked),
        {"drivers": ranked},
    )
    return {"drivers": ranked}


# 9 ---------------------------------------------------------------------------
def plan_route(rescue_id: str, driver_id: str) -> dict:
    """Plan pickup then drop-offs for the accepted recipients, nearest first, with an ETA for every stop."""
    _count_tool(rescue_id)
    rescue = _rescue(rescue_id)
    donor = store.get("donor", rescue["donor_id"])
    driver = store.get("driver", driver_id)
    if not driver:
        return {"error": f"unknown driver {driver_id}"}
    accepted = rescue.get("accepted", {})
    if not accepted:
        return {"error": "no accepted recipients to route to"}
    t = clock.now()
    leg = geo.drive(_pos(driver), _pos(donor))
    t += timedelta(minutes=leg["minutes"])
    pickup = {"kind": "pickup", "id": donor["id"], "name": donor["name"], "lat": donor["lat"], "lng": donor["lng"],
              "eta": t.isoformat(), "eta_hhmm": clock.fmt(t), "leg_km": leg["km"]}
    t += timedelta(minutes=config.STOP_SERVICE_MIN)
    here, todo, stops, sources = _pos(donor), dict(accepted), [], {leg["source"]}
    while todo:
        options = [(geo.drive(here, _pos(store.get("recipient", rid))), rid) for rid in todo]
        leg, rid = min(options, key=lambda o: o[0]["minutes"])
        sources.add(leg["source"])
        recipient = store.get("recipient", rid)
        t += timedelta(minutes=leg["minutes"])
        stops.append({"kind": "dropoff", "id": rid, "name": recipient["name"], "name_ar": recipient["name_ar"],
                      "lat": recipient["lat"], "lng": recipient["lng"], "portions": todo.pop(rid),
                      "eta": t.isoformat(), "eta_hhmm": clock.fmt(t), "leg_km": leg["km"], "status": "pending"})
        t += timedelta(minutes=config.STOP_SERVICE_MIN)
        here = _pos(recipient)
    route = {"driver_id": driver_id, "driver_start": {"lat": driver["lat"], "lng": driver["lng"]},
             "pickup": pickup, "stops": stops, "source": ", ".join(sorted(sources))}
    store.update("rescue", rescue_id, route=route, driver_id=driver_id)
    events.trace(
        rescue_id, "plan_route", "CODE",
        f"{driver['name']}: pickup {pickup['eta_hhmm']}, " + ", ".join(f"{s['name']} {s['eta_hhmm']}" for s in stops)
        + f" (routing: {route['source']})",
        {"route": route},
    )
    _ops_update(rescue_id)
    return route


# 10 --------------------------------------------------------------------------
def _gate(rescue: dict) -> list[str]:
    """The final food-safety gate. Every rule here is deterministic."""
    problems = []
    route, facts = rescue.get("route"), rescue["facts"]
    if not route:
        return ["no route planned"]
    deliver_by = _dt(rescue["safety"]["deliver_by"])
    driver = store.get("driver", route["driver_id"])
    total = 0
    for stop in route["stops"]:
        total += stop["portions"]
        if _dt(stop["eta"]) > deliver_by:
            problems.append(f"{stop['name']} ETA {stop['eta_hhmm']} is after the deliver-by time {clock.fmt(deliver_by)}")
        check = safety.dietary_check(facts, store.get("recipient", stop["id"]))
        if not check["ok"]:
            problems.append(f"{stop['name']}: {'; '.join(check['reasons'])}")
    if total > (facts.get("portions") or 0):
        problems.append(f"route carries {total} portions but only {facts.get('portions')} exist")
    if total > driver["capacity_portions"]:
        problems.append(f"{driver['name']} can carry {driver['capacity_portions']} portions, not {total}")
    if facts["storage"] in ("chilled", "frozen") and not driver["cold_box"]:
        problems.append(f"{driver['name']} has no cold box for {facts['storage']} food")
    return problems


def dispatch_and_notify(rescue_id: str) -> dict:
    """Run the food-safety gate on the planned route. If it passes, dispatch the driver and notify everyone.
    If it fails, nothing is sent and the reasons come back so the plan can be fixed."""
    _count_tool(rescue_id)
    rescue = _rescue(rescue_id)
    problems = _gate(rescue)
    if problems:
        events.trace(rescue_id, "dispatch_and_notify", "CODE", "Safety gate BLOCKED dispatch: " + "; ".join(problems), {}, "blocked")
        return {"ok": False, "violations": problems}

    route, facts = rescue["route"], rescue["facts"]
    donor = store.get("donor", rescue["donor_id"])
    driver = store.get("driver", route["driver_id"])
    safe_until = clock.fmt(_dt(rescue["safety"]["safe_until"]))
    now = clock.now()
    job = {"id": f"job-{rescue_id}", "rescue_id": rescue_id, "driver_id": driver["id"], "route": route,
           "status": "assigned", "created_at": now.isoformat()}
    store.put("job", job)
    store.update("rescue", rescue_id, status="dispatched", dispatched_at=now.isoformat(), dispatched_ts=time.time())

    stops_en = ", ".join(f"{s['name']} ({s['portions']}) {s['eta_hhmm']}" for s in route["stops"])
    stops_ar = "، ".join(f"{s['name_ar']} ({s['portions']}) {s['eta_hhmm']}" for s in route["stops"])
    total = sum(s["portions"] for s in route["stops"])
    notify.send(f"driver:{driver['id']}", messages.driver_job({
        "donor": donor["name"], "pickup_eta": route["pickup"]["eta_hhmm"], "portions": total,
        "stops_en": stops_en, "stops_ar": stops_ar}), rescue_id, sender="plenty", job=job)
    for s in route["stops"]:
        notify.send(f"recipient:{s['id']}", messages.recipient_confirmed({
            "driver": f"{driver['name']} ({driver['driver']})", "eta": s["eta_hhmm"], "portions": s["portions"],
            "safe_until": safe_until}), rescue_id, sender="plenty", stop=s)
    notify.send(f"kitchen:{donor['id']}", messages.donor_dispatched({
        "driver": f"{driver['name']} ({driver['driver']})", "pickup_eta": route["pickup"]["eta_hhmm"],
        "count": len(route["stops"]), "stops_en": stops_en, "stops_ar": stops_ar}), rescue_id, sender="plenty", card={
            "type": "pickup", "pickup_eta": route["pickup"]["eta_hhmm"], "driver": driver["name"],
            "stops": [{"name": s["name"], "name_ar": s["name_ar"], "portions": s["portions"], "eta": s["eta_hhmm"]}
                      for s in route["stops"]]})
    elapsed = time.time() - rescue["created_ts"]
    events.trace(rescue_id, "dispatch_and_notify", "CODE",
                 f"Safety gate passed. {driver['name']} dispatched; {len(route['stops']) + 2} people notified. "
                 f"Time to confirmed driver: {int(elapsed // 60)}m {int(elapsed % 60)}s.", {"job": job})
    _ops_update(rescue_id)
    return {"ok": True, "job_id": job["id"], "seconds_to_dispatch": round(elapsed)}


# After dispatch: arrival check and impact --------------------------------------
def mark_stop(rescue_id: str, stop_id: str, action: str) -> dict:
    """Driver marks a stop 'picked_up' or 'delivered'; recipient marks 'received'.
    On delivery the safety clock is checked again."""
    rescue = _rescue(rescue_id)
    route = rescue.get("route")
    if not route:
        return {"ok": False, "reason": "no route"}
    now = clock.now()
    safe_until = _dt(rescue["safety"]["safe_until"])
    if action == "picked_up":
        route["pickup"]["status"] = "done"
        route["pickup"]["done_at"] = clock.fmt(now)
        store.update("rescue", rescue_id, route=route, status="delivering")
        events.trace(rescue_id, "pickup", "CODE", f"Picked up at {clock.fmt(now)}.")
    else:
        stop = next((s for s in route["stops"] if s["id"] == stop_id), None)
        if not stop:
            return {"ok": False, "reason": "unknown stop"}
        if action == "delivered":
            stop["status"] = "delivered"
            stop["delivered_at"] = clock.fmt(now)
            if now > safe_until:
                stop["unsafe"] = True
                notify.send(f"recipient:{stop_id}", messages.unsafe_on_arrival(clock.fmt(safe_until)), rescue_id, sender="plenty", alert=True)
                events.trace(rescue_id, "arrival_check", "CODE", f"{stop['name']}: arrived {clock.fmt(now)}, AFTER safe window. Told them not to serve.", {}, "blocked")
            else:
                events.trace(rescue_id, "arrival_check", "CODE", f"{stop['name']}: arrived {clock.fmt(now)}, inside safe window (serve by {clock.fmt(safe_until)}).")
                events.emit("arrived", rescue_id, [f"recipient:{stop_id}"], stop=stop)
                recipient = store.get("recipient", stop_id) or {}
                if recipient.get("responder", "human") != "human":
                    # Partners without someone on the Plentli screen confirm the handover through their own system.
                    _confirm_receipt(rescue_id, stop, now)
        elif action == "received":
            _confirm_receipt(rescue_id, stop, now)
        store.update("rescue", rescue_id, route=route)
    _ops_update(rescue_id)
    events.emit("job", rescue_id, [f"driver:{route['driver_id']}"], route=route)
    if all(s["status"] == "received" for s in route["stops"]):
        record_impact(rescue_id)
    return {"ok": True, "route": route}


def _confirm_receipt(rescue_id: str, stop: dict, now: datetime) -> None:
    stop["status"] = "received"
    stop["received_at"] = clock.fmt(now)
    events.trace(rescue_id, "handover", "CODE", f"{stop['name']} confirmed receipt of {stop['portions']} portions.")
    events.emit("received", rescue_id, [f"recipient:{stop['id']}"], stop=stop)


def record_impact(rescue_id: str) -> dict:
    """Log the handover record. Weight and CO2e stay "not calculated" until IMPACT_FACTORS_VERIFIED is set,
    because the per-portion weight and emissions factor need a measured basis and a cited source."""
    rescue = _rescue(rescue_id)
    if rescue.get("impact"):
        return rescue["impact"]
    stops = [s for s in rescue["route"]["stops"] if s["status"] == "received" and not s.get("unsafe")]
    meals = sum(s["portions"] for s in stops)
    kg = round(meals * config.KG_PER_PORTION, 1) if config.IMPACT_FACTORS_VERIFIED else None
    impact = {
        "meals": meals, "kg": kg, "co2e_kg": round(kg * config.CO2E_PER_KG_FOOD, 1) if kg is not None else None,
        "co2e_source": config.CO2E_SOURCE if kg is not None else None,
        "recipients": len(stops),
        "handover": [{"recipient": s["name"], "portions": s["portions"], "delivered_at": s.get("delivered_at"),
                      "received_at": s.get("received_at")} for s in stops],
        "dish": rescue["facts"]["dish"], "allergens": rescue["facts"]["allergens"],
        "safe_until": clock.fmt(_dt(rescue["safety"]["safe_until"])),
        "seconds_to_dispatch": round(rescue["dispatched_ts"] - rescue["created_ts"]) if rescue.get("dispatched_ts") else None,
    }
    store.update("rescue", rescue_id, impact=impact, status="completed")
    store.put("impact", {"id": rescue_id, "donor_id": rescue["donor_id"], **impact})
    notify.send(f"kitchen:{rescue['donor_id']}", messages.impact_note(impact), rescue_id, sender="plenty",
                card={"type": "impact", "meals": meals, "recipients": len(stops)})
    weight = f"{kg} kg food, {impact['co2e_kg']} kg CO2e" if kg is not None else "weight and CO2e not calculated"
    events.trace(rescue_id, "record_impact", "CODE", f"{meals} meals received by {len(stops)} organisations ({weight}). Handover record saved.", impact)
    events.emit("impact", rescue_id, ["ops"], impact=impact)
    _ops_update(rescue_id)
    return impact
