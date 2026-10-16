# AWS deployment notes

The SAM stack is intended for `eu-north-1` in the Kisero AWS account. It creates
the private encrypted/versioned S3 archive and API Gateway HTTP API/Lambda. The
monthly budget alert is a separate CloudFormation stack in `us-east-1`, where
the AWS Budgets resource is supported. It defaults to $5 and sends actual-spend
alerts at 80% and 100%; alerts do not cap spending.

Before deployment:

1. Review that `/v1/trips` and `/v1/trips/{id}` intentionally make exact GPS
   tracks and timestamps public. `/v1/sensors` exposes recent cabin temperature
   and humidity with timestamps but no GPS location. The raw CSV and complete
   sensor archive remain private.
2. Choose the budget alert email and create `/kisero/boat/device-token` as an
   SSM `SecureString` using a randomly generated token. Keep the value only on
   the Pi in a mode-0600 secrets file. Do not enter it in Git or chat.
3. Deploy `budget-template.yaml` in `us-east-1` with `BudgetAlertEmail` and
   `MonthlyBudgetLimitUsd` parameters.
4. Deploy `template.yaml` with AWS SAM in `eu-north-1`. Save the stack's
   `ApiUrl` output.
5. Keep the website API URL aligned with the stack output. The homepage reads
   `/v1/sensors`; it refreshes every five minutes and displays only real sensor
   samples. Publish only after reviewing the public track content.
6. Put the API URL and token into `/etc/kisero/sensor.env` on the Pi (mode
   0600), install the sensor service and timer, then confirm the API
   acknowledgement matches the queued sample timestamp.

Do not upload the supplied demonstration CSV as part of provisioning. Review
its exact track locally first. Device-side Yachtdevice polling remains pending
an onboard inspection of the export page's actual download request.
