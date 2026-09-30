"""Record storage: in-memory for the demo, DynamoDB when STORE=dynamodb.

Records are plain JSON-safe dicts keyed by (kind, id). Kinds used: donor,
recipient, driver, rescue, offer, job, impact.
"""
import copy
import json
import threading
from pathlib import Path

from . import config

SEED_FILE = Path(__file__).resolve().parent.parent / "data" / "seed.json"


class MemoryStore:
    def __init__(self):
        self._lock = threading.RLock()
        self._data: dict[str, dict[str, dict]] = {}

    def put(self, kind: str, obj: dict) -> dict:
        with self._lock:
            self._data.setdefault(kind, {})[obj["id"]] = copy.deepcopy(obj)
            return copy.deepcopy(obj)

    def get(self, kind: str, obj_id: str) -> dict | None:
        with self._lock:
            obj = self._data.get(kind, {}).get(obj_id)
            return copy.deepcopy(obj) if obj else None

    def list(self, kind: str, **filters) -> list[dict]:
        with self._lock:
            items = [copy.deepcopy(o) for o in self._data.get(kind, {}).values()]
        return [o for o in items if all(o.get(k) == v for k, v in filters.items())]

    def update(self, kind: str, obj_id: str, **fields) -> dict:
        with self._lock:
            obj = self._data[kind][obj_id]
            obj.update(copy.deepcopy(fields))
            return copy.deepcopy(obj)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


class DynamoStore:
    """Single-table layout: pk = kind, sk = id, doc = JSON string."""

    def __init__(self, table_name: str, region: str):
        import boto3

        self._table = boto3.resource("dynamodb", region_name=region).Table(table_name)
        self._lock = threading.RLock()

    def put(self, kind: str, obj: dict) -> dict:
        self._table.put_item(Item={"pk": kind, "sk": obj["id"], "doc": json.dumps(obj)})
        return copy.deepcopy(obj)

    def get(self, kind: str, obj_id: str) -> dict | None:
        item = self._table.get_item(Key={"pk": kind, "sk": obj_id}, ConsistentRead=True).get("Item")
        return json.loads(item["doc"]) if item else None

    def list(self, kind: str, **filters) -> list[dict]:
        from boto3.dynamodb.conditions import Key

        items, kwargs = [], {"KeyConditionExpression": Key("pk").eq(kind), "ConsistentRead": True}
        while True:
            page = self._table.query(**kwargs)
            items += [json.loads(i["doc"]) for i in page["Items"]]
            if "LastEvaluatedKey" not in page:
                break
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
        return [o for o in items if all(o.get(k) == v for k, v in filters.items())]

    def update(self, kind: str, obj_id: str, **fields) -> dict:
        with self._lock:
            obj = self.get(kind, obj_id)
            obj.update(fields)
            return self.put(kind, obj)

    def clear(self) -> None:
        from boto3.dynamodb.conditions import Key

        with self._table.batch_writer() as batch:
            for kind in ("donor", "recipient", "driver", "rescue", "offer", "job", "impact", "photo"):
                kwargs = {"KeyConditionExpression": Key("pk").eq(kind), "ProjectionExpression": "pk, sk"}
                while True:
                    page = self._table.query(**kwargs)
                    for item in page["Items"]:
                        batch.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})
                    if "LastEvaluatedKey" not in page:
                        break
                    kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    # Shared counters and settings (used when several copies of the app run at once, as on Lambda).
    def next_number(self, name: str, start: int) -> int:
        """Atomically hand out start, start+1, ... for this counter."""
        item = self._table.update_item(
            Key={"pk": "meta", "sk": name}, UpdateExpression="ADD n :one",
            ExpressionAttributeValues={":one": 1}, ReturnValues="UPDATED_NEW")["Attributes"]
        return start + int(item["n"]) - 1

    def set_meta(self, name: str, value) -> None:
        self._table.put_item(Item={"pk": "meta", "sk": name, "doc": json.dumps(value)})

    def get_meta(self, name: str):
        item = self._table.get_item(Key={"pk": "meta", "sk": name}, ConsistentRead=True).get("Item")
        return json.loads(item["doc"]) if item and "doc" in item else None

    def delete_meta(self, name: str) -> None:
        self._table.delete_item(Key={"pk": "meta", "sk": name})


def _make_store():
    if config.STORE == "dynamodb":
        return DynamoStore(config.DDB_TABLE, config.AWS_REGION)
    return MemoryStore()


store = _make_store()


def seed() -> None:
    data = json.loads(SEED_FILE.read_text())
    for kind, key in (("donor", "donors"), ("recipient", "recipients"), ("driver", "drivers")):
        for obj in data[key]:
            store.put(kind, obj)
