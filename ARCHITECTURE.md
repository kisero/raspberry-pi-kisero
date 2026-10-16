# Yachtdevice data archive and website

## Recommendation

Use the Raspberry Pi as the collector, Amazon S3 as the long-term archive, and
small serverless APIs to receive data and serve the website. Keep the current
static kisero.org Amplify site. Do not run a continuously available VM or
database for a low-volume boat track archive.

```text
YDWG-02 (10.42.0.2:1458)
   │ local Wi-Fi, Server #3 = Memory
   ▼
Pi collector ── durable queue + SQLite cursor/dedup ── HTTPS over 4G
   │                                                  ▼
   │                                    API Gateway HTTP API + Lambda
   │                                                  │
   │                                  private S3 raw archive
   │                                  + public track JSON/GeoJSON
   │                                                  ▲
   └──────────────── kisero.org (Amplify) ── public read API
```

## Collection and retention

- Poll the Yachtdevice over the local hotspot (initial target: hourly while
  both devices are up). The manual says the export page loads the selected
  stored range and that downloads can be slow. Verify a suitable range and
  cadence against the actual unit before enabling unattended collection.
- On the Pi, retain the untouched CSV export in a durable queue until AWS
  confirms it was accepted. Parse its semicolon delimiter, UTF-8 BOM, and
  `DD/MM/YYYY, HH:MM:SS` timestamps. Sort and deduplicate points locally; keep
  a cursor and retry queue across restarts and internet outages.
- Keep the original exports in a private S3 bucket, with immutable timestamped
  object keys. Send only newly observed rows in the frequent upload batches so
  repeated exports do not consume 4G data or multiply the archive. Record
  checksums and source-export time for auditing. Never store boat data in Git.
- The supplied example is about 67 KB for 2 hours 17 minutes. If that same
  rate continued 24/7, it would be roughly 0.25 GB/year before compression;
  a decade would be around 2.5 GB. S3 Standard is a sensible first storage
  class at this scale. Avoid lifecycle transitions until actual volume
  warrants them. This is an order-of-magnitude estimate, not an AWS quote.

## Underway trip detection

Classify outings as periods moving underway, not as proof of sailing versus
motoring. Start with a configurable speed-over-ground threshold and minimum
duration; end after a configurable low-speed dwell. Use hysteresis so small
speed fluctuations do not split a trip. Tune initial thresholds using the
sample and real mooring behavior. Preserve all raw points regardless of the
classification so trips can be recalculated later.

## AWS and website

- Keep the raw S3 bucket private. The Pi sends data to an API Gateway HTTP API
  backed by Lambda; Lambda validates uploads and writes immutable raw objects
  to S3. Give the Pi a revocable, device-only upload credential with no direct
  bucket listing/read permission.
- A Lambda read endpoint serves a small trip index and per-trip GeoJSON to
  kisero.org. The user's choice is to publish exact tracks publicly, so the
  public output includes exact track coordinates and timestamps. Keep raw CSV
  measurements private unless the user separately chooses to publish those
  too. Do not put trip files in the public website Git repository or trigger
  an Amplify rebuild for each collection.
- Use the current website's region (`eu-north-1`) for the API and S3. Configure
  CORS for kisero.org and 14-day CloudWatch log retention. AWS Budgets is
  managed separately in `us-east-1`; create a monthly $5 alert for the supplied
  email address at 80% and 100%. It sends alerts; it does not stop spending.
- Skip RDS, EC2, ECS, NAT Gateway, and a continuously running analytics stack.
  They add idle or operational cost without helping this volume. Keep
  timestamped CSV as the portable source of truth; add Parquet/Athena only if
  later analysis becomes large enough to benefit.

AWS bills depend on region, free-tier eligibility, requests, storage, and
public data transfer. API Gateway HTTP APIs bill by request/data, Lambda bills
by invocation and runtime, and S3 has storage, request, and transfer charges.
At this sample's scale, storage should remain tiny; public track traffic is
the main variable cost. Check the live [S3](https://aws.amazon.com/s3/pricing/),
[API Gateway](https://aws.amazon.com/api-gateway/pricing/),
[Lambda](https://aws.amazon.com/lambda/pricing/), and
[Amplify](https://aws.amazon.com/amplify/pricing/) rates before provisioning.

## Build order

1. Onboard, confirm the YDWG-02's Memory export and actual polling/export
   behavior, then implement the collector and test retry/dedup on real exports.
2. Implement configurable underway detection and review its trip boundaries
   against actual passages.
3. Create the private archive/API and Pi-only upload credential; set budgets
   and log retention before connecting unattended upload.
4. Add the public trip map/data loader to kisero.org, publishing exact tracks
   as requested. Keep raw sensor exports private.
5. Verify end-to-end collection, public map rendering, and recovery after Pi,
   4G, or AWS outages.

No AWS resources have been created and no boat track has been uploaded or
published by this proposal.
