# Kisero data flow

The Pi records boat state and uploads to the AWS stack in `eu-north-1`.
Kisero.org is a static site hosted by Amplify. The site reads the API at
runtime, so each published voyage appears without rebuilding the website.

```text
USB GPS ────► boat tracker ────► completed voyage in SQLite
                                         │
Yacht Devices Memory ──────────────► voyage importer
Cabin sensor and PIR ──────────────► local queues
                                         │ HTTPS
                                         ▼
                       API Gateway + Lambda + DynamoDB + S3
                             │                 │
                             ▼                 ▼
                      kisero.org          SNS alarm email
```

## Voyage collection

The boat tracker confirms the start and end of an outing using the USB GPS.
The importer then reads the Yacht Devices Memory server on port 1458 over
the boat hotspot. It decodes the embedded records, matches them against the
GPS time window, and persists the selected CSV before contacting AWS. The
CSV retains each original binary record in the `Memory Record` column.
Normalized CSV timestamps and automatically imported trip timestamps use
UTC. The original September 13 manual import retains its export's local time.

The importer allows up to three minutes of missing readings near either
boundary. Gaps larger than four logging intervals or an incomplete page
trigger a second download and merge. A gap of ten minutes inside a live
outing leaves it queued for retry. SQLite retains each valid export until the
API acknowledges its SHA-256 digest.

The historical importer can merge several Memory captures. It infers an end
from ten minutes of stopped readings or a ten-minute gap followed by a later
record. It skips outings shorter than ten minutes and avoids duplicating
existing voyages. It can improve a previous Memory import when the same trip
boundaries have more recovered points. See the [backfill runbook](docs/boat-automation.md#historical-backfill).

## Storage and access

| Data | Private storage | Public feed |
| --- | --- | --- |
| Voyage exports | Immutable, encrypted CSV objects in S3, keyed by SHA-256 digest | Trip summaries and per-trip JSON with GPS tracks, timestamps and sailing readings |
| Cabin temperature and humidity | Individual samples in S3 | Up to 31 days of recent readings |
| Alarm and connectivity | Alarm events in S3 and recent history in DynamoDB | Read-only snapshots, history and live WebSocket updates |
| Current boat and phone GPS | Short-lived DynamoDB items for status and Auto alarm | Boat state and named area when available |

The internet chart tracks successful Pi contact with AWS. It marks a gap
longer than 90 seconds as no contact. The chart records reachability, which
can be affected by the Pi, the uplink, or the backend.

The Pi uses a device token stored in AWS Systems Manager Parameter Store
and in the device's private runtime environment. The alarm page and
OwnTracks each use a separate credential derived from that token.
An armed buzzer trigger enters a DynamoDB notification outbox. A Lambda
worker publishes the email through SNS.

The design uses request-based services and object storage. Keep the
existing $5 budget alert separate from the application stack. See the
[AWS deployment runbook](aws/DEPLOYMENT.md).

## Homepage snapshot

`GET /v1/home` reads the last published cabin observation, coarse boat status
and alarm device state from a single DynamoDB item. The existing S3 index
supplies the trip summaries. Normal authenticated Pi uploads update the
cached fields independently. The boat status cache retains the last valid
Moored or Sailing state through gaps in GPS reception.

The website starts with a browser copy or the fallback bundled by Amplify at
build time. It refreshes the shared snapshot while visible. The homepage
displays the latest heartbeat receipt time in AWS as the last update, in
the visitor's local time. Last known readings stay visible between reports.
A cabin observation has its own timestamp and is normally sampled every
five minutes.

See the [website snapshot documentation](https://github.com/kisero/kisero.org#homepage-snapshot).
