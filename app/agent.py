"""The rescue agent.

AGENT_MODE=bedrock: a Strands agent on Claude (Amazon Bedrock) chooses which tool to call next.
AGENT_MODE=mock:    a deterministic planner calls the same tools in the same spirit, so the
                    whole demo runs with no AWS access. Its reasoning lines are labelled "AI (mock)".
"""
import threading
import traceback

from . import config, events, notify, tools
from .store import store

SYSTEM_PROMPT = """You are Plenty, a food-rescue coordinator for Dubai. A commercial kitchen has surplus food.
Your job: get as much of it as possible to people who need it tonight, safely, with no phone calls.

How to work:
1. classify_surplus. If portions or cooking time are missing, ask_donor one short question (English and Arabic), then classify_surplus again.
2. get_safe_window. If urgency is EXPIRED, stop: the kitchen has already been told.
3. find_recipients, then check_dietary for every eligible recipient.
4. Decide the split: prefer priority-1 partners (shelters, community kitchens, care homes) over community fridges,
   nearer before farther, never more than a recipient's need. Call validate_allocation, then send_offers.
5. If anyone declines or does not answer and portions are unplaced, re-plan: call find_recipients again
   (declined partners are excluded), check_dietary for new ones, and offer the remaining portions. At most 3 rounds.
6. find_drivers, pick the best (the donor's own returning van with a cold box is preferred), plan_route, then dispatch_and_notify.
7. If dispatch_and_notify is blocked, read the violations and fix the plan (another driver, or fewer stops); never try to bypass it.

Rules: the food-safety tools are authoritative; you cannot change a serve-by time or a dietary result.
Before each tool call, write one short sentence saying what you are doing and why. Finish with a two-line summary."""


def _ai(rescue_id: str, text: str, mock: bool = True) -> None:
    events.trace(rescue_id, "reasoning", "AI (mock)" if mock else "AI", text)


def _allocate(remaining: int, candidates: list[dict], dietary: dict) -> dict[str, int]:
    split = {}
    for c in candidates:
        if remaining <= 0:
            break
        if not dietary.get(c["id"], {}).get("ok"):
            continue
        take = min(c["need_tonight"], remaining)
        if take > 0:
            split[c["id"]] = take
            remaining -= take
    return split


def run_mock(rescue_id: str) -> None:
    facts = tools.classify_surplus(rescue_id)
    if facts["missing"]:
        q_en = "How many portions is it, and what time was it cooked?" if len(facts["missing"]) > 1 else (
            "How many portions is it?" if "portions" in facts["missing"] else "What time was it cooked?")
        q_ar = "كم عدد الوجبات، ومتى تم طبخها؟" if len(facts["missing"]) > 1 else (
            "كم عدد الوجبات؟" if "portions" in facts["missing"] else "متى تم طبخها؟")
        _ai(rescue_id, f"Missing {', '.join(facts['missing'])}; asking the kitchen one question instead of guessing.")
        reply = tools.ask_donor(rescue_id, q_en, q_ar)
        if reply.get("timed_out"):
            _ai(rescue_id, "No answer from the kitchen; stopping rather than guessing food-safety facts.")
            store.update("rescue", rescue_id, status="failed")
            return
        facts = tools.classify_surplus(rescue_id)
        if facts["missing"]:
            store.update("rescue", rescue_id, status="failed")
            return

    window = tools.get_safe_window(rescue_id)
    if window.get("urgency") in (None, "EXPIRED"):
        return
    _ai(rescue_id, f"Urgency {window['urgency']}: {window['minutes_left']} minutes of safe time left. Matching nearby partners first.")

    checked: set[str] = set()
    for round_no in range(1, 4):
        rescue = store.get("rescue", rescue_id)
        remaining = facts["portions"] - sum(rescue.get("accepted", {}).values())
        if remaining <= 0:
            break
        found = tools.find_recipients(rescue_id)
        new_ids = [e["id"] for e in found["eligible"] if e["id"] not in checked]
        if new_ids:
            tools.check_dietary(rescue_id, new_ids)
            checked.update(new_ids)
        rescue = store.get("rescue", rescue_id)
        split = _allocate(remaining, found["eligible"], rescue.get("dietary", {}))
        if not split:
            _ai(rescue_id, f"No eligible recipient left for the remaining {remaining} portions.")
            break
        names = {r["id"]: r["name"] for r in store.list("recipient")}
        _ai(rescue_id, ("Split" if round_no == 1 else "Re-plan") + ": " + ", ".join(f"{p} to {names[r]}" for r, p in split.items())
            + ". Priority partners first, nearest first, never above their need.")
        if not tools.validate_allocation(rescue_id, split)["ok"]:
            break
        result = tools.send_offers(rescue_id, split)
        if result.get("unplaced_portions", 0) > 0 and (result["declined"] or result["timed_out"]):
            _ai(rescue_id, f"{len(result['declined']) + len(result['timed_out'])} partner(s) said no. Re-planning the {result['unplaced_portions']} unplaced portions.")

    rescue = store.get("rescue", rescue_id)
    if not rescue.get("accepted"):
        _ai(rescue_id, "Nobody could take the food tonight.")
        notify.send(f"kitchen:{rescue['donor_id']}", {"en": "Sorry, no partner could take this food tonight.",
                                                      "ar": "عذرًا، لم تتمكن أي جهة من استلام هذا الطعام الليلة."}, rescue_id, sender="plenty")
        store.update("rescue", rescue_id, status="failed")
        return

    drivers = tools.find_drivers(rescue_id)["drivers"]
    for d in drivers[:3]:
        _ai(rescue_id, f"Choosing {d['name']} ({d['driver']}): {d['status']}, {d['minutes_to_pickup']:.0f} min away"
            + (", has a cold box." if d["cold_box"] else ", no cold box."))
        tools.plan_route(rescue_id, d["id"])
        if tools.dispatch_and_notify(rescue_id)["ok"]:
            break
        _ai(rescue_id, "Safety gate blocked that plan; trying the next driver.")

    rescue = store.get("rescue", rescue_id)
    unplaced = facts["portions"] - sum(rescue.get("accepted", {}).values())
    if unplaced > 0 and rescue["status"] == "dispatched":
        notify.send(f"kitchen:{rescue['donor_id']}", {
            "en": f"{unplaced} portions could not be placed tonight; please keep them chilled or use them for staff meals.",
            "ar": f"لم نتمكن من توزيع {unplaced} وجبة الليلة؛ يُرجى حفظها مبردة أو تقديمها للموظفين."}, rescue_id, sender="plenty")


def run_bedrock(rescue_id: str) -> None:
    from strands import Agent, tool
    from strands.models import BedrockModel

    @tool
    def classify_surplus() -> dict:
        """Read the kitchen's photo and note: dish, portions, allergens, halal, cooking time, storage."""
        return tools.classify_surplus(rescue_id)

    @tool
    def ask_donor(question_en: str, question_ar: str) -> dict:
        """Ask the kitchen one short question (give English and Arabic) and wait for the reply."""
        return tools.ask_donor(rescue_id, question_en, question_ar)

    @tool
    def get_safe_window() -> dict:
        """Compute the serve-by and deliver-by times from the food-safety rule table."""
        return tools.get_safe_window(rescue_id)

    @tool
    def find_recipients() -> dict:
        """List recipients that are open, in range, reachable in time, and still need food tonight."""
        return tools.find_recipients(rescue_id)

    @tool
    def check_dietary(recipient_ids: list[str]) -> dict:
        """Check the food against each recipient's allergen, halal and storage rules."""
        return tools.check_dietary(rescue_id, recipient_ids)

    @tool
    def validate_allocation(allocation: dict[str, int]) -> dict:
        """Check a split of portions (recipient id -> portions) before offering it."""
        return tools.validate_allocation(rescue_id, allocation)

    @tool
    def send_offers(allocation: dict[str, int]) -> dict:
        """Send offers (recipient id -> portions) and wait for accept, decline or no answer."""
        return tools.send_offers(rescue_id, allocation)

    @tool
    def find_drivers() -> dict:
        """Rank available drivers for the accepted load."""
        return tools.find_drivers(rescue_id)

    @tool
    def plan_route(driver_id: str) -> dict:
        """Plan pickup and drop-offs for the accepted recipients with the given driver, with ETAs."""
        return tools.plan_route(rescue_id, driver_id)

    @tool
    def dispatch_and_notify() -> dict:
        """Run the final food-safety gate; if it passes, dispatch the driver and notify everyone."""
        return tools.dispatch_and_notify(rescue_id)

    buffer: list[str] = []

    def on_event(**kwargs):
        if kwargs.get("data"):
            buffer.append(kwargs["data"])
        started = kwargs.get("event", {}).get("contentBlockStart", {}).get("start", {}).get("toolUse")
        if (started or kwargs.get("complete")) and "".join(buffer).strip():
            _ai(rescue_id, "".join(buffer).strip(), mock=False)
            buffer.clear()

    agent = Agent(
        model=BedrockModel(model_id=config.BEDROCK_MODEL_ID, region_name=config.BEDROCK_REGION, max_tokens=4096),
        system_prompt=SYSTEM_PROMPT,
        tools=[classify_surplus, ask_donor, get_safe_window, find_recipients, check_dietary,
               validate_allocation, send_offers, find_drivers, plan_route, dispatch_and_notify],
        callback_handler=on_event,
    )
    agent("A kitchen just reported surplus food. Run the rescue.")
    if "".join(buffer).strip():
        _ai(rescue_id, "".join(buffer).strip(), mock=False)


def _run(rescue_id: str) -> None:
    try:
        if config.AGENT_MODE == "bedrock":
            try:
                run_bedrock(rescue_id)
            except Exception as exc:
                # Keep the live demo alive if Bedrock is unreachable before the agent has done anything.
                rescue = store.get("rescue", rescue_id)
                if not config.BEDROCK_FALLBACK or (rescue and rescue.get("tool_calls")):
                    raise
                traceback.print_exc()
                events.trace(rescue_id, "error", "CODE",
                             f"Bedrock unavailable ({type(exc).__name__}); running the mock planner instead.", {}, "warn")
                run_mock(rescue_id)
        else:
            run_mock(rescue_id)
    except Exception as exc:
        traceback.print_exc()
        events.trace(rescue_id, "error", "CODE", f"Agent stopped: {type(exc).__name__}: {exc}", {}, "blocked")
        rescue = store.get("rescue", rescue_id)
        if rescue and rescue.get("status") not in ("dispatched", "delivering", "completed"):
            store.update("rescue", rescue_id, status="failed")
    finally:
        rescue = store.get("rescue", rescue_id)
        if rescue:
            events.emit("rescue", rescue_id, ["ops"], rescue=tools.public_rescue(rescue))


def start(rescue_id: str) -> None:
    threading.Thread(target=_run, args=(rescue_id,), daemon=True, name=f"rescue-{rescue_id}").start()
