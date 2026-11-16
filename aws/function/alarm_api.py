"""Alarm control, durable motion records, and public live WebSocket updates."""
import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boat
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
    public_control = {name: value for name, value in control().items() if name != "mode"}
    return {"control": public_control, "device": plain(device) if device else None,
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


HISTORY_DAYS = 31
_connectivity_started = None
_extended_history_started = None

def connectivity_start():
    global _connectivity_started
    if _connectivity_started is None:
        _connectivity_started = table().get_item(Key={"pk": "CONNECTIVITY", "sk": "START"}, ConsistentRead=True).get("Item", {}).get("startedAt")
    return _connectivity_started


def record_connectivity(received_at):
    """Record server receipt, never the device's potentially delayed clock."""
    global _connectivity_started
    if connectivity_start() is None:
        try:
            table().put_item(Item={"pk": "CONNECTIVITY", "sk": "START", "startedAt": received_at},
                             ConditionExpression="attribute_not_exists(pk)")
            _connectivity_started = received_at
        except ClientError as error:
            if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            connectivity_start()
    epoch = int(datetime.fromisoformat(received_at.replace("Z", "+00:00")).timestamp())
    global _extended_history_started
    if _extended_history_started is None:
        result = table().update_item(Key={"pk": "CONNECTIVITY", "sk": "HISTORY"},
            UpdateExpression="SET startedAt = if_not_exists(startedAt, :now)",
            ExpressionAttributeValues={":now": received_at}, ReturnValues="ALL_NEW")
        _extended_history_started = result["Attributes"]["startedAt"]
    # At most one entry per 30-second bin; a busy PIR doesn't inflate the history.
    bucket = datetime.fromtimestamp(epoch // 30 * 30, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    try:
        table().put_item(Item={"pk": "CONNECTIVITY", "sk": "BEAT#" + bucket,
            "receivedAt": received_at, "expiresAt": epoch + HISTORY_DAYS * 86400},
            ConditionExpression="attribute_not_exists(pk)")
    except ClientError as error:
        if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise


def query_rows(**query):
    dynamo = table()
    while True:
        result = dynamo.query(**query)
        yield from result.get("Items", [])
        if not result.get("LastEvaluatedKey"):
            return
        query["ExclusiveStartKey"] = result["LastEvaluatedKey"]


def coverage_start(days):
    clock = datetime.now(timezone.utc)
    recent = clock - timedelta(days=7)
    start = table().get_item(Key={"pk": "CONNECTIVITY", "sk": "HISTORY"}).get("Item", {}).get("startedAt")
    extended = datetime.fromisoformat(start.replace("Z", "+00:00")) if start else recent
    return max(clock - timedelta(days=days), min(recent, extended))


def connectivity_history(days=1):
    if days == 1:
        cutoff = datetime.now(timezone.utc) - timedelta(days=1, seconds=90)
        started = connectivity_start()
    else:
        coverage = coverage_start(days)
        cutoff = coverage - timedelta(seconds=90)
        installation = connectivity_start()
        started = max(installation, coverage.isoformat(timespec="milliseconds").replace("+00:00", "Z")) if installation else None
    cutoff_stamp = cutoff.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    rows = query_rows(KeyConditionExpression=Key("pk").eq("CONNECTIVITY") & Key("sk").between("BEAT#" + cutoff_stamp, "BEAT#~"),
                      ProjectionExpression="receivedAt")
    if days == 1:
        return {"startedAt": started, "beats": [row["receivedAt"] for row in rows], "graceSeconds": 90}
    intervals = []
    for row in rows:
        stamp = int(datetime.fromisoformat(row["receivedAt"].replace("Z", "+00:00")).timestamp())
        if intervals and stamp <= intervals[-1][1]:
            intervals[-1][1] = stamp + 90
        else:
            intervals.append([stamp, stamp + 90])
    return {"startedAt": started, "intervals": intervals, "graceSeconds": 90}


def alarm_history(days):
    cutoff = coverage_start(days).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    rows = query_rows(KeyConditionExpression=Key("pk").eq("ALARM") & Key("sk").between("EVENT#" + cutoff, "EVENT#~"))
    return [row for row in rows if row["armed"] is True or row["kind"] == "disarmed"]


def device_status(payload):
    for field in ("armed", "motion", "sounding", "ready"):
        if not isinstance(payload.get(field), bool):
            raise ValueError("invalid device status")
    version = payload.get("controlVersion")
    if not isinstance(version, int) or isinstance(version, bool) or version < 0:
        raise ValueError("invalid control version")
    item = {key: payload[key] for key in ("armed", "motion", "sounding", "ready", "controlVersion")}
    item["reportedAt"] = timestamp(payload.get("observedAt"))
    item["receivedAt"] = now()
    item["armingUntil"] = timestamp(payload["armingUntil"]) if payload.get("armingUntil") else None
    try:
        table().put_item(Item={"pk": "ALARM", "sk": "DEVICE", **item},
            ConditionExpression="attribute_not_exists(reportedAt) OR reportedAt <= :t",
            ExpressionAttributeValues={":t": item["reportedAt"]})
    except ClientError as error:
        if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise

    record_connectivity(item["receivedAt"])
    return item["receivedAt"]


def http(event, context, authorized, get_token):
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("rawPath", "")
    headers = {k.lower(): v for k, v in event.get("headers", {}).items()}
    if method == "GET" and path == "/v1/alarm":
        days = (event.get("queryStringParameters") or {}).get("days")
        if days in ("7", "30"):
            result = reply(200, {"events": alarm_history(int(days)), "connectivity": connectivity_history(int(days))})
            result["headers"]["cache-control"] = "public, max-age=120"
            return result
        result = state()
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        records = table().query(KeyConditionExpression=Key("pk").eq("ALARM") & Key("sk").between(
            "EVENT#" + cutoff, "EVENT#~"), ScanIndexForward=False, Limit=500)
        result["events"] = plain(list(reversed(records.get("Items", []))))
        result["connectivity"] = connectivity_history()
        return reply(200, result)
    if path == "/v1/alarm/control":
        # A purpose-specific capability is derived from the existing device secret.
        # It can control the alarm but cannot upload data using the device API.
        expected = hmac.new(get_token().encode(), b"kisero-alarm-control-v1", hashlib.sha256).hexdigest()
        if not hmac.compare_digest(headers.get("authorization", ""), "Bearer " + expected):
            return reply(401, {"error": "private control link required"})
    elif path == "/v1/alarm/owntracks":
        if not boat.phone_authorized(headers.get("authorization", ""), get_token()):
            return reply(401, {"error": "unauthorized"})
    elif path == "/v1/alarm/boat" and method == "GET":
        return reply(200, boat.public(table(), time.time()))
    elif path in {"/v1/alarm/device", "/v1/motion", "/v1/alarm/boat"}:
        if not authorized(headers):
            return reply(401, {"error": "unauthorized"})
    else:
        return reply(404, {"error": "not found"})
    if method == "GET" and path == "/v1/alarm/device":
        return reply(200, {"control": control()})
    if method == "GET" and path == "/v1/alarm/control":
        current = control()
        boat_fix, phone_fix = boat.read(table(), "BOAT"), boat.read(table(), "PHONE")
        _, reason = boat.decide(boat_fix, phone_fix, time.time())
        return reply(200, {"mode": current.get("mode", "manual"), "reason": reason})
    if path in {"/v1/alarm/owntracks", "/v1/alarm/boat"} and len(event.get("body") or "") > 4096:
        return reply(413, {"error": "location message too large"})
    try:
        payload = json.loads(event.get("body") or ("{}" if path != "/v1/alarm/owntracks" else '{"_type":"ignore"}'))
        if not isinstance(payload, dict):
            raise ValueError("object required")
        if method == "POST" and path == "/v1/alarm/control":
            automatic = payload.get("mode") == "auto"
            if not automatic and not isinstance(payload.get("armed"), bool):
                raise ValueError("armed must be true or false")
            if automatic:
                # Preserve the currently requested state until both feeds justify a change.
                expression = "SET #m=:m, updatedAt=:t, armed=if_not_exists(armed,:a) ADD #v :one"
            else:
                expression = "SET #m=:m, updatedAt=:t, armed=:a ADD #v :one"
            table().update_item(Key=boat.KEY, UpdateExpression=expression,
                ExpressionAttributeNames={"#m": "mode", "#v": "version"},
                ExpressionAttributeValues={":a": False if automatic else payload["armed"],
                                           ":m": "auto" if automatic else "manual", ":t": now(), ":one": 1})
            if automatic:
                boat.auto(table(), now)
            publish()
            return reply(200, state())
        if method == "POST" and path in {"/v1/alarm/owntracks", "/v1/alarm/boat"}:
            kind = "PHONE" if path.endswith("owntracks") else "BOAT"
            if kind == "PHONE" and payload.get("_type") != "location":
                return reply(200, [])
            if boat.save(table(), boat.fix(payload, kind, time.time())) and boat.auto(table(), now):
                publish()
            return reply(200, [] if kind == "PHONE" else {"accepted": True})
        if method == "POST" and path == "/v1/alarm/device":
            received_at = device_status(payload)
            publish({"connectivityBeat": received_at, "connectivityStartedAt": connectivity_start()})
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
                    "expiresAt": int(time.time()) + HISTORY_DAYS * 86400, **row}, ConditionExpression="attribute_not_exists(pk)")
            except ClientError as error:
                if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
                    raise
            publish({"event": row})
            return reply(200, {"accepted": True, "id": event_id})
    except (ValueError, TypeError, json.JSONDecodeError):
        return reply(400, {"error": "invalid alarm request"})
    return reply(405, {"error": "method not allowed"})
