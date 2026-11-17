"""Public last-known homepage readings, updated independently of page visits."""
import logging
from decimal import Decimal

KEY = {"pk": "PUBLIC", "sk": "HOME"}
FIELDS = {
    "position": ("observedAt", "state", "location"),
    "device": ("receivedAt", "reportedAt", "armed", "ready", "motion", "sounding",
               "armingUntil", "controlVersion"),
    "cabin": ("observedAt", "temperatureC", "humidityPct"),
}
LOG = logging.getLogger(__name__)


def merge_snapshot(previous, changes):
    result = dict(previous)
    for name, fields in FIELDS.items():
        item = changes.get(name)
        stamp_key = fields[0]
        if not item or stamp_key not in item:
            continue
        if name == "position" and item.get("state") not in ("moored", "sailing"):
            continue
        prior_stamp = result.get(name, {}).get(stamp_key)
        if prior_stamp is None or item[stamp_key] > prior_stamp:
            result[name] = {field: item[field] for field in fields if field in item}
    return result


def record(table, name, item):
    public = merge_snapshot({}, {name: item}).get(name)
    if public is None:
        return
    values = {field: Decimal(str(value)) if isinstance(value, float) else value
              for field, value in public.items()}
    stamp = FIELDS[name][0]
    try:
        table.update_item(
            Key=KEY,
            UpdateExpression="SET #section = :reading",
            ConditionExpression="attribute_not_exists(#section.#stamp) OR #section.#stamp < :stamp",
            ExpressionAttributeNames={"#section": name, "#stamp": stamp},
            ExpressionAttributeValues={":reading": values, ":stamp": values[stamp]},
        )
    except Exception as error:
        code = getattr(error, "response", {}).get("Error", {}).get("Code")
        if code != "ConditionalCheckFailedException":
            LOG.warning("Could not store homepage %s snapshot (%s)", name, type(error).__name__)
