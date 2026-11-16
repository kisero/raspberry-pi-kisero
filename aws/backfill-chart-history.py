#!/usr/bin/env python3
"""Restore retained sensor and armed alarm records for the public chart windows."""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError


def main():
    region = "eu-north-1"
    stack = "kisero-yachtdevice"
    cloudformation = boto3.client("cloudformation", region_name=region)
    s3 = boto3.client("s3", region_name=region)
    bucket = cloudformation.describe_stack_resource(StackName=stack, LogicalResourceId="ArchiveBucket")["StackResourceDetail"]["PhysicalResourceId"]
    name = cloudformation.describe_stack_resource(StackName=stack, LogicalResourceId="AlarmTable")["StackResourceDetail"]["PhysicalResourceId"]
    table = boto3.resource("dynamodb", region_name=region).Table(name)
    cutoff = datetime.now(timezone.utc) - timedelta(days=31)
    stamp = cutoff.isoformat(timespec="seconds").replace("+00:00", "Z")
    paginator = s3.get_paginator("list_objects_v2")

    def read(key):
        with s3.get_object(Bucket=bucket, Key=key)["Body"] as body:
            return json.load(body)

    def archived(kind):
        prefix = f"raw/{kind}/"
        start = prefix + cutoff.strftime("%Y/%m/%d")
        keys = (obj["Key"] for page in paginator.paginate(Bucket=bucket, Prefix=prefix, StartAfter=start)
                for obj in page.get("Contents", []))
        with ThreadPoolExecutor(max_workers=8) as pool:
            return [row for row in pool.map(read, keys) if row["observedAt"] >= stamp]

    samples = archived("sensors")
    events = [row for row in archived("motion") if row["armed"] is True or row["kind"] == "disarmed"]
    key = "published/sensors/history.json"
    for attempt in range(5):
        obj = s3.get_object(Bucket=bucket, Key=key)
        with obj["Body"] as body:
            history = json.load(body)
        merged = {row["observedAt"]: row for row in samples}
        merged.update((row["observedAt"], row) for row in history["samples"])
        history["samples"] = [merged[time_key] for time_key in sorted(merged) if time_key >= stamp]
        try:
            s3.put_object(Bucket=bucket, Key=key, Body=json.dumps(history, separators=(",", ":")).encode(),
                          ContentType="application/json", ServerSideEncryption="AES256", IfMatch=obj["ETag"])
            break
        except ClientError as error:
            if error.response["ResponseMetadata"]["HTTPStatusCode"] not in (409, 412) or attempt == 4:
                raise
            time.sleep(0.1 * (attempt + 1))
    for row in events:
        observed = datetime.fromisoformat(row["observedAt"].replace("Z", "+00:00"))
        expires = int((observed + timedelta(days=31)).timestamp())
        try:
            table.put_item(Item={"pk": "ALARM", "sk": f"EVENT#{row['observedAt']}#{row['id']}",
                                 "expiresAt": expires, **row},
                           ConditionExpression="attribute_not_exists(pk) OR expiresAt < :expiry",
                           ExpressionAttributeValues={":expiry": expires})
        except ClientError as error:
            if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
    print(f"History contains {len(history['samples'])} cabin readings and considered {len(events)} archived alarm events.")


if __name__ == "__main__":
    main()
