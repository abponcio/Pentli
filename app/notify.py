"""Deliver a message to one person's screen, and optionally to an SNS topic."""
import json

from . import config, events

_sns = None


def send(audience: str, texts: dict, rescue_id: str | None = None, **extra) -> dict:
    """audience is e.g. "kitchen:k1", "recipient:r3", "driver:d1". texts maps language to text."""
    event = events.emit("message", rescue_id, [audience], texts=texts, **extra)
    if config.NOTIFY == "sns" and config.SNS_TOPIC_ARN:
        _publish_sns(audience, texts, rescue_id)
    return event


def _publish_sns(audience: str, texts: dict, rescue_id: str | None) -> None:
    global _sns
    try:
        if _sns is None:
            import boto3

            _sns = boto3.client("sns", region_name=config.AWS_REGION)
        _sns.publish(
            TopicArn=config.SNS_TOPIC_ARN,
            Message=json.dumps({"audience": audience, "rescue_id": rescue_id, "texts": texts}, ensure_ascii=False),
            MessageAttributes={"audience": {"DataType": "String", "StringValue": audience}},
        )
    except Exception as exc:
        events.emit("warning", rescue_id, ["ops"], text=f"SNS publish failed: {type(exc).__name__}")
