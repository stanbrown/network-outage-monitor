# Network Outage Monitor

A small Dockerized web app that checks one endpoint every 5 seconds and records when outages start, when service recovers, and how long each outage lasted.

The backend uses an HTTP request instead of raw ICMP ping so it can run in a normal Docker container. SQLite stores only outage starts and the first successful recovery check, while routine successful checks remain in memory.

## Run

```powershell
docker compose up --build
```

Then open:

```text
http://localhost:8000
```

## Configuration

Set these environment variables in `docker-compose.yml`:

- `TARGET_URL`: endpoint to check. Default: `https://www.google.com/generate_204`
- `CHECK_INTERVAL_SECONDS`: check interval. Default: `5`
- `REQUEST_TIMEOUT_SECONDS`: request timeout. Default: `4`
- `RETENTION_DAYS`: number of days of check history to keep. Default: `7`
- `DATA_DIR`: SQLite storage location. Default in Docker: `/data`

Records older than the retention period are removed at startup and then hourly. Consecutive failed checks are shown as one outage ending at the first successful check.
