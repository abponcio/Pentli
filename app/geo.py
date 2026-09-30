"""Drive times between two points.

ROUTING=location uses Amazon Location Service (geo-routes CalculateRoutes).
Anything else, or any error from Location, falls back to straight-line distance
times a road factor at an average city speed, and says so in the result.
"""
import math

from . import config

_client = None


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def _estimate(a, b) -> dict:
    km = haversine_km(a, b) * config.ROAD_FACTOR
    return {"km": round(km, 1), "minutes": round(km / config.AVG_SPEED_KMH * 60, 1), "source": "estimate"}


def _location_client():
    global _client
    if _client is None:
        import boto3

        _client = boto3.client("geo-routes", region_name=config.AWS_REGION)
    return _client


def drive(a: tuple[float, float], b: tuple[float, float]) -> dict:
    """Distance and drive time from a to b, each given as (lat, lng)."""
    if config.ROUTING != "location":
        return _estimate(a, b)
    try:
        resp = _location_client().calculate_routes(
            Origin=[a[1], a[0]], Destination=[b[1], b[0]], TravelMode="Car", DepartNow=True
        )
        summary = resp["Routes"][0]["Summary"]
        return {
            "km": round(summary["Distance"] / 1000, 1),
            "minutes": round(summary["Duration"] / 60, 1),
            "source": "amazon-location",
        }
    except Exception as exc:  # no credentials, no network, or a service error
        result = _estimate(a, b)
        result["source"] = f"estimate (Location unavailable: {type(exc).__name__})"
        return result
