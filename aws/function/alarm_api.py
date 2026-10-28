"""Alarm control, durable motion records, and public live WebSocket updates."""
import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def plain(value):
    if isinstance(value, Decimal):
        return int(value) if value == int(value) else float(value)
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items() if k not in {"pk", "sk", "expiresAt"}}
    if isinstance(value, list):
        return [plain(v) for v in value]
    return value


def table():
    return boto3.resource("dynamodb").Table(os.environ["ALARM_TABLE"])


def reply(status, body):
    return {"statusCode": status, "headers": {
        "content-type": "application/json", "cache-control": "no-store",
        "access-control-allow-origin": os.environ["WEB_ORIGIN"]},
        "body": json.dumps(plain(body))}


def control():
    return plain(table().get_item(Key={"pk": "ALARM", "sk": "CONTROL"}, ConsistentRead=True).get(
        "Item", {"armed": False, "version": 0, "updatedAt": None}))


def state():
    device = table().get_item(Key={"pk": "ALARM", "sk": "DEVICE"}, ConsistentRead=True).get("Item")
    return {"control": control(), "device": plain(device) if device else None,
            "serverTime": now(), "websocketUrl": os.environ["ALARM_WEBSOCKET_URL"]}


def publish(extra=None):
    """Push status to connected readers; stale sockets are removed, not fatal."""
    packet = {"type": "alarm-update", **state(), **(extra or {})}
    client = boto3.client("apigatewaymanagementapi", endpoint_url=os.environ["ALARM_WS_MANAGEMENT_URL"])
    result = table().query(KeyConditionExpression=Key("pk").eq("CONNECTION"))
    for connection in result.get("Items", []):
        if int(connection["expiresAt"]) < time.time():
            table().delete_item(Key={"pk": "CONNECTION", "sk": connection["sk"]})
            continue
        try:
            client.post_to_connection(ConnectionId=connection["sk"], Data=json.dumps(plain(packet)).encode())
        except client.exceptions.GoneException:
            table().delete_item(Key={"pk": "CONNECTION", "sk": connection["sk"]})
        except ClientError:
            # A slow reader must not make an already persisted upload fail.
            pass


def websocket(event, context):
    request = event["requestContext"]
    key = {"pk": "CONNECTION", "sk": request["connectionId"]}
    if request["routeKey"] == "$connect":
        table().put_item(Item={**key, "expiresAt": int(time.time()) + 7200})
    elif request["routeKey"] == "$disconnect":
        table().delete_item(Key=key)
    elif request["routeKey"] == "$default":
        # Keep-alive only. WebSocket clients can never arm/disarm or write events.
        client = boto3.client("apigatewaymanagementapi", endpoint_url=os.environ["ALARM_WS_MANAGEMENT_URL"])
        try:
            client.post_to_connection(ConnectionId=request["connectionId"], Data=b'{"type":"pong"}')
        except client.exceptions.GoneException:
            pass
    return {"statusCode": 200, "body": "ok"}


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("observedAt is required")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise ValueError("invalid observation time")
    return parsed.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def device_status(payload):
    for field in ("armed", "motion", "sounding", "ready"):
        if not isinstance(payload.get(field), bool):
            raise ValueError("invalid device status")
    version = payload.get("controlVersion")
    if not isinstance(version, int) or isinstance(version, bool) or version < 0:
        raise ValueError("invalid control version")
    item = {key: payload[key] for key in ("armed", "motion", "sounding", "ready", "controlVersion")}
    item["reportedAt"] = timestamp(payload.get("observedAt"))
    item["armingUntil"] = timestamp(payload["armingUntil"]) if payload.get("armingUntil") else None
    try:
        table().put_item(Item={"pk": "ALARM", "sk": "DEVICE", **item},
            ConditionExpression="attribute_not_exists(reportedAt) OR reportedAt <= :t",
            ExpressionAttributeValues={":t": item["reportedAt"]})
    except ClientError as error:
        if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise


def http(event, context, authorized, get_token):
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("rawPath", "")
    headers = {k.lower(): v for k, v in event.get("headers", {}).items()}
    if method == "GET" and path == "/v1/alarm":
        result = state()
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        records = table().query(KeyConditionExpression=Key("pk").eq("ALARM") & Key("sk").between(
            "EVENT#" + cutoff, "EVENT#~"), ScanIndexForward=False, Limit=500)
        result["events"] = plain(list(reversed(records.get("Items", []))))
        return reply(200, result)
    if method == "POST" and path == "/v1/alarm/control":
        # A purpose-specific capability is derived from the existing device secret.
        # It can control the alarm but cannot upload data using the device API.
        expected = hmac.new(get_token().encode(), b"kisero-alarm-control-v1", hashlib.sha256).hexdigest()
        if not hmac.compare_digest(headers.get("authorization", ""), "Bearer " + expected):
            return reply(401, {"error": "private control link required"})
    elif path in {"/v1/alarm/device", "/v1/motion"}:
        if not authorized(headers):
            return reply(401, {"error": "unauthorized"})
    else:
        return reply(404, {"error": "not found"})
    if method == "GET" and path == "/v1/alarm/device":
        return reply(200, {"control": control()})
    try:
        payload = json.loads(event.get("body") or "{}")
        if not isinstance(payload, dict):
            raise ValueError("object required")
        if method == "POST" and path == "/v1/alarm/control":
            if not isinstance(payload.get("armed"), bool):
                raise ValueError("armed must be true or false")
            table().update_item(Key={"pk": "ALARM", "sk": "CONTROL"},
                UpdateExpression="SET armed=:a, updatedAt=:t ADD #v :one",
                ExpressionAttributeNames={"#v": "version"},
                ExpressionAttributeValues={":a": payload["armed"], ":t": now(), ":one": 1})
            publish()
            return reply(200, state())
        if method == "POST" and path == "/v1/alarm/device":
            device_status(payload)
            publish()
            return reply(200, {"accepted": True, "control": control()})
        if method == "POST" and path == "/v1/motion":
            event_id = payload.get("id", "")
            if not isinstance(event_id, str) or len(event_id) != 32 or any(c not in "0123456789abcdef" for c in event_id):
                raise ValueError("invalid event id")
            kind = payload.get("kind")
            if kind not in {"motion", "armed", "disarmed", "triggered", "silenced", "ready"}:
                raise ValueError("invalid event kind")
            if not isinstance(payload.get("motion"), bool) or not isinstance(payload.get("armed"), bool):
                raise ValueError("invalid event state")
            row = {"id": event_id, "observedAt": timestamp(payload.get("observedAt")),
                   "kind": kind, "motion": payload["motion"], "armed": payload["armed"]}
            raw = json.dumps(row, separators=(",", ":")).encode()
            try:
                boto3.client("s3").put_object(Bucket=os.environ["BUCKET"],
                    Key="raw/motion/" + row["observedAt"][:10].replace("-", "/") + "/" + event_id + ".json",
                    Body=raw, ContentType="application/json", ServerSideEncryption="AES256", IfNoneMatch="*")
            except ClientError as error:
                if error.response.get("ResponseMetadata", {}).get("HTTPStatusCode") != 412:
                    raise
            try:
                table().put_item(Item={"pk": "ALARM", "sk": "EVENT#" + row["observedAt"] + "#" + event_id,
                    "expiresAt": int(time.time()) + 7 * 86400, **row}, ConditionExpression="attribute_not_exists(pk)")
            except ClientError as error:
                if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
                    raise
            publish({"event": row})
            return reply(200, {"accepted": True, "id": event_id})
    except (ValueError, TypeError, json.JSONDecodeError):
        return reply(400, {"error": "invalid alarm request"})
    return reply(405, {"error": "method not allowed"})
