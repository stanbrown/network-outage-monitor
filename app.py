from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "data"))
DB_PATH = DATA_DIR / "network_monitor.sqlite3"

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))
TARGET_URL = os.environ.get("TARGET_URL", "https://www.google.com/generate_204")
CHECK_INTERVAL_SECONDS = float(os.environ.get("CHECK_INTERVAL_SECONDS", "5"))
REQUEST_TIMEOUT_SECONDS = float(os.environ.get("REQUEST_TIMEOUT_SECONDS", "4"))
RETENTION_DAYS = int(os.environ.get("RETENTION_DAYS", "7"))
URL_OPENER = build_opener(ProxyHandler({}))
LAST_PROBE_OK: bool | None = None
LATEST_CHECK: dict | None = None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")




def get_db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            checked_at INTEGER NOT NULL,
            ok INTEGER NOT NULL,
            latency_ms REAL,
            status_code INTEGER,
            error TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_checks_checked_at ON checks (checked_at)")
    conn.commit()
    return conn


def record_check(ok: bool, latency_ms: float | None, status_code: int | None, error: str | None) -> None:
    global LAST_PROBE_OK, LATEST_CHECK

    checked_at = int(time.time())
    with get_db() as conn:
        previous_row = conn.execute(
            "SELECT ok FROM checks ORDER BY checked_at DESC, id DESC LIMIT 1"
        ).fetchone()
        previous_stored_ok = bool(previous_row[0]) if previous_row is not None else None
        state_changed = previous_stored_ok is not ok

        # Successful checks are only stored when they close an outage. Failed
        # checks are only stored when they begin one.
        if state_changed and (not ok or previous_stored_ok is False):
            conn.execute(
                """
                INSERT INTO checks (checked_at, ok, latency_ms, status_code, error)
                VALUES (?, ?, ?, ?, ?)
                """,
                (checked_at, 1 if ok else 0, latency_ms, status_code, error),
            )
            conn.commit()

    LATEST_CHECK = {
        "time": datetime.fromtimestamp(checked_at, timezone.utc).isoformat().replace("+00:00", "Z"),
        "ok": ok,
        "latencyMs": latency_ms,
        "statusCode": status_code,
        "error": error,
    }

    if ok != LAST_PROBE_OK:
        timestamp = utc_now_iso()
        if ok:
            message = "Target is online" if LAST_PROBE_OK is None else "Connection restored"
        else:
            detail = error or (f"HTTP {status_code}" if status_code is not None else "No response")
            message = f"Outage detected: {detail}"
        print(f"{timestamp} {message}", flush=True)
        LAST_PROBE_OK = ok

def prune_old_checks() -> int:
    cutoff_epoch = int(time.time()) - (RETENTION_DAYS * 24 * 60 * 60)
    with get_db() as conn:
        cursor = conn.execute(
            """
            DELETE FROM checks
            WHERE checked_at < ?
              AND NOT (
                  ok = 0
                  AND id = (
                      SELECT id
                      FROM checks
                      ORDER BY checked_at DESC, id DESC
                      LIMIT 1
                  )
              )
            """,
            (cutoff_epoch,),
        )
        conn.commit()
        return cursor.rowcount



def probe_target() -> None:
    start = time.perf_counter()
    request = Request(TARGET_URL, method="GET", headers={"User-Agent": "network-monitor/1.0"})
    try:
        with URL_OPENER.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            response.read(64)
            elapsed_ms = (time.perf_counter() - start) * 1000
            status = response.getcode()
            record_check(200 <= status < 500, elapsed_ms, status, None)
    except HTTPError as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000
        record_check(exc.code < 500, elapsed_ms, exc.code, str(exc))
    except (TimeoutError, URLError, OSError) as exc:
        record_check(False, None, None, str(exc))


def monitor_loop() -> None:
    next_prune_at = 0.0
    while True:
        probe_target()
        if time.monotonic() >= next_prune_at:
            prune_old_checks()
            next_prune_at = time.monotonic() + (60 * 60)
        time.sleep(CHECK_INTERVAL_SECONDS)


def fetch_outages() -> dict:
    start_epoch = int(time.time()) - (RETENTION_DAYS * 24 * 60 * 60)
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT checked_at, ok, latency_ms, status_code, error
            FROM checks
            WHERE checked_at >= ?
            ORDER BY checked_at ASC
            """,
            (start_epoch,),
        ).fetchall()

    points = [
        {
            "time": datetime.fromtimestamp(row[0], timezone.utc).isoformat().replace("+00:00", "Z"),
            "ok": bool(row[1]),
            "latencyMs": row[2],
            "statusCode": row[3],
            "error": row[4],
        }
        for row in rows
    ]
    latest = LATEST_CHECK or (points[-1] if points else None)
    outages = []
    outage_start = None

    for point in points:
        if not point["ok"] and outage_start is None:
            outage_start = point["time"]
        elif point["ok"] and outage_start is not None:
            start_time = datetime.fromisoformat(outage_start.replace("Z", "+00:00"))
            end_time = datetime.fromisoformat(point["time"].replace("Z", "+00:00"))
            outages.append(
                {
                    "start": outage_start,
                    "end": point["time"],
                    "durationSeconds": max(0, round((end_time - start_time).total_seconds())),
                    "ongoing": False,
                }
            )
            outage_start = None

    if outage_start is not None:
        start_time = datetime.fromisoformat(outage_start.replace("Z", "+00:00"))
        outages.append(
            {
                "start": outage_start,
                "end": None,
                "durationSeconds": max(0, round((datetime.now(timezone.utc) - start_time).total_seconds())),
                "ongoing": True,
            }
        )

    return {
        "targetUrl": TARGET_URL,
        "intervalSeconds": CHECK_INTERVAL_SECONDS,
        "retentionDays": RETENTION_DAYS,
        "generatedAt": utc_now_iso(),
        "outages": list(reversed(outages)),
        "latest": latest,
    }


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self) -> None:
        if self.path == "/api/outages":
            payload = json.dumps(fetch_outages()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if self.path == "/health":
            payload = b"ok"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if self.path == "/":
            self.path = "/index.html"
        super().do_GET()


class Server(ThreadingHTTPServer):
    daemon_threads = True


def main() -> None:
    get_db().close()
    pruned_count = prune_old_checks()
    threading.Thread(target=monitor_loop, daemon=True).start()
    server = Server((HOST, PORT), Handler)
    print(f"Network monitor listening on http://{HOST}:{PORT}", flush=True)
    print(f"Checking {TARGET_URL} every {CHECK_INTERVAL_SECONDS:g} seconds", flush=True)
    print(
        f"Keeping {RETENTION_DAYS} days of data (removed {pruned_count} old records at startup)",
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
