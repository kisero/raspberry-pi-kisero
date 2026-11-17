# AWS deployment

The live application uses the `kisero-yachtdevice` SAM stack in
`eu-north-1`. It provides the private encrypted and versioned S3 archive,
the HTTP API and Lambda handlers, the alarm and connectivity history table,
the WebSocket feed, and an SNS topic for alarm email.

When updating the application, use the existing stack, bucket, SSM parameter,
and API. See the template parameters and retain the deployed values.

```sh
sam build --template-file aws/template.yaml
sam deploy --stack-name kisero-yachtdevice --region eu-north-1 \
  --resolve-s3 --capabilities CAPABILITY_IAM
```

## Restore or verify a deployment

1. In Systems Manager Parameter Store, use the existing
   `/kisero/boat/device-token` SecureString. For a new stack, generate a token
   privately. Keep the value in Parameter Store and the Pi's root-owned
   `/etc/kisero/sensor.env`, with file mode 0600.
2. Use the stack's `ApiUrl` for `KISERO_API_URL` on the Pi and keep the
   website's API base aligned with it. See the [Pi restore steps](../README.md#restoring-the-pi).
3. Confirm the Pi can reach the API and its service timers are active.
   Public read endpoints include `/v1/trips`, `/v1/trips/{id}`,
   `/v1/sensors`, `/v1/alarm`, and `/v1/alarm/boat`. Completed voyages
   include exact GPS tracks and timestamps. The live boat endpoint
   shows state and a named area when available.
4. In SNS, check the intended email address is subscribed and confirmed
   on the **Kisero Boat Alarm** topic. A confirmed recipient receives an
   email when the backend accepts an armed buzzer trigger.
5. For voyage backfills and OwnTracks setup, use the
   [boat automation runbook](../docs/boat-automation.md).

The monthly budget is a separate CloudFormation stack in `us-east-1`.
Deploy [budget-template.yaml](budget-template.yaml) with `BudgetAlertEmail`
and `MonthlyBudgetLimitUsd` when setting it up. The default is $5, with
actual-spend email alerts at 80% and 100%. These alerts do not cap spending.
