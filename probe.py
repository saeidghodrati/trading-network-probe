import asyncio
import json
import os
import socket
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import websockets


DATA_DIR = Path(os.getenv("PROBE_DATA_DIR", "/data"))
INTERVAL = max(
    30,
    int(os.getenv("PROBE_INTERVAL_SECONDS", "60"))
)

WS_URL = os.getenv(
    "PROBE_WS_URL",
    "wss://ws.postman-echo.com/raw"
)

STATE_FILE = DATA_DIR / "state.json"
LOG_FILE = DATA_DIR / "probe.jsonl"

TARGETS = {
    "wallex": {
        "host": "api.wallex.ir",
        "url": "https://api.wallex.ir/hector/web/v1/markets",
    },
    "nobitex": {
        "host": "api.nobitex.ir",
        "url": "https://api.nobitex.ir/market/stats?srcCurrency=btc&dstCurrency=rls",
    },
}


def now():
    return datetime.now(timezone.utc).isoformat()


def save_state(state):
    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    tmp = STATE_FILE.with_suffix(".tmp")

    tmp.write_text(
        json.dumps(state)
    )

    tmp.replace(STATE_FILE)


def load_state():
    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    try:
        state = json.loads(
            STATE_FILE.read_text()
        )
    except Exception:
        state = {}

    state["starts"] = (
        int(state.get("starts", 0)) + 1
    )

    state["probe_seq"] = int(
        state.get("probe_seq", 0)
    )

    state["ip_changes"] = int(
        state.get("ip_changes", 0)
    )

    state["first_seen"] = (
        state.get("first_seen") or now()
    )

    state["last_start"] = now()

    save_state(state)

    return state


def dns_probe(host):
    start = time.perf_counter()

    try:
        rows = socket.getaddrinfo(
            host,
            443,
            type=socket.SOCK_STREAM
        )

        addresses = sorted({
            x[4][0]
            for x in rows
        })

        return {
            "ok": True,
            "latency_ms": round(
                (
                    time.perf_counter()
                    - start
                ) * 1000,
                2
            ),
            "addresses": addresses[:6]
        }

    except Exception as e:
        return {
            "ok": False,
            "error":
                f"{type(e).__name__}: {e}"
        }


def http_probe(url):
    start = time.perf_counter()

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent":
                "trading-network-probe/1.0",
            "Accept":
                "application/json,*/*"
        }
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=12
        ) as response:

            response.read(256)

            return {
                "reachable": True,
                "status": response.status,
                "latency_ms": round(
                    (
                        time.perf_counter()
                        - start
                    ) * 1000,
                    2
                )
            }

    except urllib.error.HTTPError as e:
        return {
            "reachable": True,
            "status": e.code,
            "latency_ms": round(
                (
                    time.perf_counter()
                    - start
                ) * 1000,
                2
            )
        }

    except Exception as e:
        return {
            "reachable": False,
            "status": None,
            "error":
                f"{type(e).__name__}: {e}"
        }


def get_ip():
    request = urllib.request.Request(
        "https://api.ipify.org?format=json",
        headers={
            "User-Agent":
                "trading-network-probe/1.0"
        }
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=10
        ) as response:

            return json.loads(
                response.read()
            ).get("ip")

    except Exception:
        return None


def memory_mb():
    try:
        for line in Path(
            "/proc/self/status"
        ).read_text().splitlines():

            if line.startswith("VmRSS:"):
                return round(
                    int(
                        line.split()[1]
                    ) / 1024,
                    2
                )
    except Exception:
        pass

    return None


async def websocket_probe():
    start = time.perf_counter()

    try:
        async with websockets.connect(
            WS_URL,
            open_timeout=12,
            ping_interval=20,
            ping_timeout=20
        ) as ws:

            msg = (
                f"probe-{time.time_ns()}"
            )

            await ws.send(msg)

            reply = await asyncio.wait_for(
                ws.recv(),
                timeout=12
            )

            return {
                "ok": reply == msg,
                "latency_ms": round(
                    (
                        time.perf_counter()
                        - start
                    ) * 1000,
                    2
                ),
                "url": WS_URL
            }

    except Exception as e:
        return {
            "ok": False,
            "url": WS_URL,
            "error":
                f"{type(e).__name__}: {e}"
        }


async def main():
    state = load_state()

    print(
        json.dumps({
            "event": "started",
            "time": now(),
            "starts": state["starts"]
        }),
        flush=True
    )

    while True:
        state["probe_seq"] += 1

        ip = await asyncio.to_thread(
            get_ip
        )

        old_ip = state.get("last_ip")

        if (
            ip
            and old_ip
            and ip != old_ip
        ):
            state["ip_changes"] += 1

        if ip:
            state["last_ip"] = ip

        record = {
            "time": now(),

            "probe_seq":
                state["probe_seq"],

            "process_starts":
                state["starts"],

            "outbound_ip":
                ip,

            "ip_changes":
                state["ip_changes"],

            "dns": {
                name:
                    await asyncio.to_thread(
                        dns_probe,
                        target["host"]
                    )
                for name, target
                in TARGETS.items()
            },

            "https": {
                name:
                    await asyncio.to_thread(
                        http_probe,
                        target["url"]
                    )
                for name, target
                in TARGETS.items()
            },

            "websocket":
                await websocket_probe(),

            "memory_rss_mb":
                memory_mb()
        }

        state["last_seen"] = (
            record["time"]
        )

        save_state(state)

        with LOG_FILE.open(
            "a",
            encoding="utf-8"
        ) as f:
            f.write(
                json.dumps(record)
                + "\n"
            )

        print(
            json.dumps(record),
            flush=True
        )

        await asyncio.sleep(
            INTERVAL
        )


if __name__ == "__main__":
    asyncio.run(main())
