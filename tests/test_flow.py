"""End-to-end rescue in mock mode: intake, safety window, offers, a decline, re-plan, dispatch, delivery, impact."""
import os
import time

os.environ.update({
    "AGENT_MODE": "mock", "STORE": "memory", "ROUTING": "haversine", "NOTIFY": "inapp",
    "DEMO_CLOCK": "19:40", "SIM_RESPONSE_SECONDS": "0.2", "OFFER_TIMEOUT_SECONDS": "3",
})

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.store import store  # noqa: E402

client = TestClient(app)


def wait_for(rescue_id, statuses, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        rescue = store.get("rescue", rescue_id)
        if rescue["status"] in statuses:
            return rescue
        time.sleep(0.1)
    raise AssertionError(f"rescue stuck in {store.get('rescue', rescue_id)['status']}")


def start(note):
    client.post("/api/reset")
    store.update("recipient", "r3", responder="auto_decline")  # the judge declines
    resp = client.post("/api/kitchen/message", data={"donor_id": "k1", "text": note})
    assert resp.status_code == 200
    return resp.json()["rescue_id"]


def test_full_rescue_with_decline_and_replan():
    rid = start("50 chicken biryani, has cashews, cooked at 6, room temperature")
    rescue = wait_for(rid, {"dispatched", "failed", "expired"})
    assert rescue["status"] == "dispatched", rescue
    assert rescue["facts"]["portions"] == 50
    assert "tree_nuts" in rescue["facts"]["allergens"]
    assert rescue["dietary"]["r2"]["ok"] is False  # nut-free care home excluded
    assert "r3" in rescue["declined"]  # judge declined
    assert rescue["accepted"] == {"r1": 30, "r4": 20}  # re-planned to the fridge
    assert rescue["route"]["driver_id"] == "d1"  # returning HelloChef van
    assert rescue["tool_calls"] >= 10

    client.post("/api/stops", json={"rescue_id": rid, "action": "picked_up"})
    for stop in rescue["route"]["stops"]:
        client.post("/api/stops", json={"rescue_id": rid, "stop_id": stop["id"], "action": "delivered"})
        client.post("/api/stops", json={"rescue_id": rid, "stop_id": stop["id"], "action": "received"})
    done = store.get("rescue", rid)
    assert done["status"] == "completed"
    assert done["impact"]["meals"] == 50


def test_arabic_note():
    rid = start("عندنا خمسين وجبة برياني دجاج، فيها كاجو، مطبوخة الساعة ٦")
    rescue = wait_for(rid, {"dispatched", "failed", "expired"})
    assert rescue["facts"]["portions"] == 50
    assert rescue["facts"]["language"] == "ar"
    assert "tree_nuts" in rescue["facts"]["allergens"]
    assert rescue["status"] == "dispatched"


def test_expired_food_is_refused():
    rid = start("40 chicken curry cooked at 2pm, room temperature")
    rescue = wait_for(rid, {"dispatched", "failed", "expired"})
    assert rescue["status"] == "expired"
    assert not rescue.get("offers")
