"""Surplus photos: kept in memory, and uploaded to S3 when PHOTO_BUCKET is set."""
import base64
import threading

from . import config, events

_lock = threading.Lock()
_photos: dict[str, dict] = {}


def save(rescue_id: str, data: bytes, content_type: str) -> None:
    fmt = {"image/png": "png", "image/webp": "webp", "image/gif": "gif"}.get(content_type, "jpeg")
    with _lock:
        _photos[rescue_id] = {"b64": base64.b64encode(data).decode(), "format": fmt, "content_type": content_type}
    if config.PHOTO_BUCKET:
        try:
            import boto3

            boto3.client("s3", region_name=config.AWS_REGION).put_object(
                Bucket=config.PHOTO_BUCKET, Key=f"surplus/{rescue_id}.{fmt}", Body=data, ContentType=content_type
            )
            if config.SERVERLESS:
                from .store import store

                store.put("photo", {"id": rescue_id, "format": fmt, "content_type": content_type})
        except Exception as exc:
            events.emit("warning", rescue_id, ["ops"], text=f"S3 photo upload failed: {type(exc).__name__}")


def get(rescue_id: str) -> dict | None:
    with _lock:
        photo = _photos.get(rescue_id)
    if photo or not (config.SERVERLESS and config.PHOTO_BUCKET):
        return photo
    # Another copy of the app took the upload: read it back from S3.
    from .store import store

    meta = store.get("photo", rescue_id)
    if not meta:
        return None
    import boto3

    body = boto3.client("s3", region_name=config.AWS_REGION).get_object(
        Bucket=config.PHOTO_BUCKET, Key=f"surplus/{rescue_id}.{meta['format']}")["Body"].read()
    return {"b64": base64.b64encode(body).decode(), "format": meta["format"], "content_type": meta["content_type"]}


def clear() -> None:
    with _lock:
        _photos.clear()
