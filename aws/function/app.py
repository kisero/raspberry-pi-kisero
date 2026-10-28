"""API handler: private immutable raw uploads, public exact-track JSON reads."""
import hashlib
import hmac
import json
import math
import os
import time
import alarm_api
from datetime import datetime, timedelta, timezone
import boto3
from botocore.exceptions import ClientError

s3 = boto3.client("s3")
ssm = boto3.client("ssm")


def response(status, body, origin):
    return {"statusCode": status, "headers": {"content-type": "application/json",
            "access-control-allow-origin": origin, "cache-control": "public, max-age=60"},
            "body": json.dumps(body)}


_cached_token = None
_token_until = 0

def get_token():
    global _cached_token, _token_until
    if time.monotonic() >= _token_until:
        _cached_token = ssm.get_parameter(Name=os.environ["TOKEN_PARAMETER"], WithDecryption=True)["Parameter"]["Value"]
        _token_until = time.monotonic() + 300
    return _cached_token

def authorized(headers):
    normalized = {key.lower(): value for key, value in headers.items()}
    token = normalized.get("authorization", "")
    expected = get_token()
    return token.startswith("Bearer ") and hmac.compare_digest(token[7:], expected)


def normalize_sensor_sample(payload):
    observed_at = payload.get("observedAt")
    temperature = payload.get("temperatureC")
    humidity = payload.get("humidityPct")
    if not isinstance(observed_at, str) or not isinstance(temperature, (int, float)) or isinstance(temperature, bool) or not isinstance(humidity, (int, float)) or isinstance(humidity, bool):
        return None
    try:
        parsed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    parsed = parsed.astimezone(timezone.utc).replace(microsecond=0)
    temperature = float(temperature)
    humidity = float(humidity)
    if not math.isfinite(temperature) or not math.isfinite(humidity) or not (-40 <= temperature <= 125) or not (0 <= humidity <= 100):
        return None
    return {"observedAt": parsed.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "temperatureC": round(temperature, 2), "humidityPct": round(humidity, 1)}


def handler(event, context):
    if "connectionId" in event.get("requestContext", {}):
        return alarm_api.websocket(event, context)
    if event.get("rawPath", "").startswith("/v1/alarm") or event.get("rawPath") == "/v1/motion":
        return alarm_api.http(event, context, authorized, get_token)
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("rawPath", "")
    origin = os.environ["WEB_ORIGIN"]
    bucket = os.environ["BUCKET"]
    if method == "POST" and path == "/v1/ingest":
        if not authorized(event.get("headers", {})):
            return response(401, {"error": "unauthorized"}, origin)
        payload = json.loads(event.get("body") or "{}")
        raw = payload.get("rawCsvBase64")
        derived = payload.get("trips", [])
        if not raw or not isinstance(derived, list):
            return response(400, {"error": "rawCsvBase64 and trips are required"}, origin)
        import base64
        raw_bytes = base64.b64decode(raw, validate=True)
        if not raw_bytes or len(raw_bytes) > 5 * 1024 * 1024:
            return response(413, {"error": "CSV export is empty or too large"}, origin)
        digest = hashlib.sha256(raw_bytes).hexdigest()
        try:
            s3.put_object(Bucket=bucket, Key=f"raw/{digest}.csv", Body=raw_bytes,
                          ContentType="text/csv", ServerSideEncryption="AES256", IfNoneMatch="*")
        except ClientError as error:
            if error.response.get("ResponseMetadata", {}).get("HTTPStatusCode") != 412:
                raise
        summaries = []
        if len(derived) > 100:
            return response(400, {"error": "too many trips"}, origin)
        for trip in derived:
            trip_id = trip.get("id", "")
            if not isinstance(trip_id, str) or not trip_id.replace("T", "").replace("Z", "").replace("_", "").isalnum():
                return response(400, {"error": "invalid trip id"}, origin)
            track = trip.get("track")
            if not isinstance(track, list) or not track or len(track) > 20000:
                return response(400, {"error": "invalid track"}, origin)
            for point in track:
                if (not isinstance(point, list) or len(point) != 4 or
                    not all(isinstance(value, (int, float)) for value in point[:2] + point[3:]) or
                    not (-180 <= point[0] <= 180 and -90 <= point[1] <= 90) or
                    not isinstance(point[2], str)):
                    return response(400, {"error": "invalid track point"}, origin)
            safe_trip = {key: trip[key] for key in ("id", "start", "end", "pointCount", "distanceNm", "averageSogKn", "maxSogKn") if key in trip}
            safe_trip["track"] = track
            if len(safe_trip) != 8:
                return response(400, {"error": "trip summary is incomplete"}, origin)
            s3.put_object(Bucket=bucket, Key=f"published/trips/{trip_id}.json",
                          Body=json.dumps(safe_trip, separators=(",", ":")).encode(),
                          ContentType="application/json", ServerSideEncryption="AES256")
            summaries.append({key: safe_trip[key] for key in ("id", "start", "end", "pointCount", "distanceNm", "averageSogKn", "maxSogKn")})
        index = {"schemaVersion": 1, "trips": summaries}
        s3.put_object(Bucket=bucket, Key="published/index.json", Body=json.dumps(index).encode(),
                      ContentType="application/json", ServerSideEncryption="AES256")
        return response(200, {"accepted": True, "sha256": digest}, origin)
    if method == "POST" and path == "/v1/sensors":
        if not authorized(event.get("headers", {})):
            return response(401, {"error": "unauthorized"}, origin)
        try:
            payload = json.loads(event.get("body") or "{}")
        except (TypeError, json.JSONDecodeError):
            return response(400, {"error": "invalid JSON"}, origin)
        if not isinstance(payload, dict):
            return response(400, {"error": "sensor sample must be a JSON object"}, origin)
        sample = normalize_sensor_sample(payload)
        if sample is None:
            return response(400, {"error": "invalid sensor sample"}, origin)
        raw_bytes = json.dumps(sample, separators=(",", ":")).encode("utf-8")
        digest = hashlib.sha256(raw_bytes).hexdigest()
        date_path = sample["observedAt"][:10].replace("-", "/")
        try:
            s3.put_object(Bucket=bucket, Key=f"raw/sensors/{date_path}/{digest}.json", Body=raw_bytes,
                          ContentType="application/json", ServerSideEncryption="AES256", IfNoneMatch="*")
        except ClientError as error:
            if error.response.get("ResponseMetadata", {}).get("HTTPStatusCode") != 412:
                raise
        try:
            history_object = s3.get_object(Bucket=bucket, Key="published/sensors/history.json")
            history = json.loads(history_object["Body"].read())
        except ClientError as error:
            if error.response.get("ResponseMetadata", {}).get("HTTPStatusCode") != 404:
                raise
            history = {"schemaVersion": 1, "samples": []}
        samples = [row for row in history.get("samples", []) if row.get("observedAt") != sample["observedAt"]]
        samples.append(sample)
        samples.sort(key=lambda row: row["observedAt"])
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        samples = [row for row in samples
                   if datetime.fromisoformat(row["observedAt"].replace("Z", "+00:00")) >= cutoff]
        updated = {"schemaVersion": 1, "updatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
                   "samples": samples}
        s3.put_object(Bucket=bucket, Key="published/sensors/history.json",
                      Body=json.dumps(updated, separators=(",", ":")).encode("utf-8"),
                      ContentType="application/json", ServerSideEncryption="AES256")
        return response(200, {"accepted": True, "observedAt": sample["observedAt"]}, origin)
    if method == "GET" and path == "/v1/trips":
        try:
            obj = s3.get_object(Bucket=bucket, Key="published/index.json")
        except ClientError as error:
            if error.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404:
                return response(200, {"schemaVersion": 1, "trips": []}, origin)
            raise
        return response(200, json.loads(obj["Body"].read()), origin)
    if method == "GET" and path == "/v1/sensors":
        try:
            obj = s3.get_object(Bucket=bucket, Key="published/sensors/history.json")
        except ClientError as error:
            if error.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404:
                return response(200, {"schemaVersion": 1, "samples": []}, origin)
            raise
        return response(200, json.loads(obj["Body"].read()), origin)
    prefix = "/v1/trips/"
    if method == "GET" and path.startswith(prefix):
        trip_id = path[len(prefix):]
        if not trip_id.replace("T", "").replace("Z", "").replace("_", "").isalnum():
            return response(400, {"error": "invalid trip id"}, origin)
        try:
            obj = s3.get_object(Bucket=bucket, Key=f"published/trips/{trip_id}.json")
        except ClientError as error:
            if error.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404:
                return response(404, {"error": "not found"}, origin)
            raise
        return response(200, json.loads(obj["Body"].read()), origin)
    return response(404, {"error": "not found"}, origin)
