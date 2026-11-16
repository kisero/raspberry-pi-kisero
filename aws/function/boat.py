"""Boat and phone updates; exact fixes never enter the public alarm payload."""
import base64
import hashlib
import hmac
import math
import time
from decimal import Decimal
from botocore.exceptions import ClientError

KEY = {"pk": "ALARM", "sk": "CONTROL"}
THRESHOLD = 300
BOAT_FRESH = 120
PHONE_FRESH = 300
PLACES = [(36.487, -4.952, 1600, "Puerto Banús"), (36.508, -4.886, 1600, "Marbella")]


def read(table, kind):
    return table.get_item(Key={"pk": "POSITION", "sk": kind}, ConsistentRead=True).get("Item")


def distance(a, b):
    lat1, lat2 = [math.radians(float(p["lat"])) for p in (a, b)]
    dl = math.radians(float(b["lon"]) - float(a["lon"]))
    v = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dl/2)**2
    return 12742000 * math.asin(math.sqrt(min(1, max(0, v))))


def fix(payload, kind, clock):
    lat, lon, observed = [payload.get(k) for k in ("lat", "lon", "tst")]
    fields = [(lat, -90, 90), (lon, -180, 180), (observed, clock-86400, clock+30)]
    if kind == "PHONE":
        fields.append((payload.get("acc"), 1, 10000))
    if any(type(v) not in (int, float) or not (low <= v <= high) for v, low, high in fields):
        raise ValueError("invalid location or timestamp")
    result = {"pk": "POSITION", "sk": kind, "lat": Decimal(str(lat)), "lon": Decimal(str(lon)),
              "tst": Decimal(str(observed)), "expiresAt": int(clock) + 3600}
    if kind == "PHONE":
        result["acc"] = Decimal(str(payload["acc"]))
    else:
        if payload.get("state") not in ("moored", "sailing", "unknown"):
            raise ValueError("invalid boat state")
        result["state"] = payload["state"]
    return result


def save(table, item):
    try:
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(tst) OR tst < :t",
                       ExpressionAttributeValues={":t": item["tst"]})
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        return False


def public(table, clock):
    boat = read(table, "BOAT")
    if not boat or float(boat["tst"]) < clock - BOAT_FRESH:
        return {"state": "unknown"}
    nearest = [(distance(boat, {"lat": lat, "lon": lon}), radius, name) for lat, lon, radius, name in PLACES]
    meters, radius, name = min(nearest)
    return {"state": boat["state"], "location": name if meters <= radius else None,
            "observedAt": float(boat["tst"])}


def decide(boat, phone, clock):
    if not boat or float(boat["tst"]) < clock - BOAT_FRESH:
        return None, "boat-gps-unavailable"
    if boat["state"] == "sailing":
        return False, "underway"
    if boat["state"] != "moored":
        return None, "boat-gps-unavailable"
    if not phone or float(phone["tst"]) < clock - PHONE_FRESH or float(phone["acc"]) > 60:
        return None, "phone-location-unavailable"
    meters = distance(boat, phone)
    # Reserve 25 m for the boat receiver; don't switch if uncertainty straddles the limit.
    uncertainty = float(phone["acc"]) + 25
    if meters - uncertainty > THRESHOLD:
        return True, "away"
    if meters + uncertainty <= THRESHOLD:
        return False, "near"
    return None, "near-boundary"


def auto(table, control, stamp):
    if control.get("mode") != "auto":
        return False
    desired, _ = decide(read(table, "BOAT"), read(table, "PHONE"), time.time())
    if desired is None or desired == control["armed"]:
        return False
    try:
        table.update_item(Key=KEY, UpdateExpression="SET armed=:a, updatedAt=:t ADD #v :one",
                          ConditionExpression="#m=:auto AND #v=:current",
                          ExpressionAttributeNames={"#m": "mode", "#v": "version"},
                          ExpressionAttributeValues={":a": desired, ":t": stamp(), ":one": 1,
                                                     ":auto": "auto", ":current": control["version"]})
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        return False


def phone_authorized(header, device_token):
    secret = hmac.new(device_token.encode(), b"kisero-owntracks-v1", hashlib.sha256).hexdigest()
    expected = base64.b64encode(("kisero:" + secret).encode()).decode()
    return hmac.compare_digest(header, "Basic " + expected)
