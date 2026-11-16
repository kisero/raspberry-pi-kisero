"""Deliver armed buzzer alerts to the private SNS email subscription."""
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import boto3


def handler(event, context):
    sns = boto3.client("sns")
    topic = os.environ["ALARM_EMAIL_TOPIC"]
    if event.get("test") is True:
        sent = sns.publish(TopicArn=topic, Subject="Kisero alarm email test",
                           Message="This is a test of the Kisero boat alarm email. No alarm was triggered.")
        return {"messageId": sent["MessageId"]}

    for record in event["Records"]:
        if record["eventName"] != "INSERT":
            continue
        item = record["dynamodb"]["NewImage"]
        observed = datetime.fromisoformat(item["observedAt"]["S"].replace("Z", "+00:00"))
        local = observed.astimezone(ZoneInfo("Europe/Madrid"))
        sns.publish(TopicArn=topic, Subject="Kisero boat alarm triggered",
                    Message=f"The buzzer sounded on Kisero at {local:%d %b %Y, %H:%M:%S %Z}.\n\n"
                            "View the movement chart at https://kisero.org/#motion")
    return {"accepted": True}
