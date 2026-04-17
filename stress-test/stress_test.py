#!/usr/bin/env python3
"""
RoboParam WebSocket Aggregator — Stress Test Client

Architecture context
--------------------
The aggregator is a *broadcast-only* WebSocket server.  The data pipeline is:

    User/client  →  SQS  →  worker3  →  Isaac Sim  →  Redis  →  Aggregator  →  WebSocket clients

WebSocket clients only receive SimResult messages — they never send.  To stress
the aggregator in isolation (without AWS/Isaac Sim), this test injects messages
directly into Redis and measures how quickly they arrive at all connected clients.

What is measured
----------------
* Connection establishment time (per client)
* Publish throughput (msgs/sec injected into Redis)
* Receive throughput (msgs/sec aggregated across all clients)
* Per-message end-to-end latency: Redis publish  →  WebSocket receive
  (latency percentiles: p50, p75, p95, p99, p99.9)
* Per-client delivery rate (fraction of published messages received)
* Error counts

Usage
-----
  # Quick smoke test (10 clients, 10,000 msgs)
  python stress_test.py --clients 10 --messages 10000

  # Full benchmark: test several concurrency levels with 500,000 messages each
  python stress_test.py --clients 1 5 10 50 100 200 --messages 500000

  # Save results to CSV for plotting
  python stress_test.py --clients 1 10 50 100 --output results.csv

  # Custom endpoints
  python stress_test.py --ws-url ws://192.168.1.5:8082/ws/results \\
                        --redis-host 192.168.1.3

  # Rate-limited publish (simulate realistic arrival rate)
  python stress_test.py --rate 5000 --clients 50

Requirements
------------
  pip install redis websockets
  Python >= 3.9
"""

import argparse
import asyncio
import csv
import json
import math
import random
import statistics
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional

try:
    import redis
    import websockets
except ImportError:
    print("Missing dependencies.  Install with:\n  pip install redis websockets")
    sys.exit(1)


# ──────────────────────────────────────────────────────────────────
# Defaults  (all overridable via CLI flags)
# ──────────────────────────────────────────────────────────────────
DEFAULT_WS_URL        = "ws://localhost:8082/ws/results"
DEFAULT_REDIS_HOST    = "192.168.1.3"
DEFAULT_REDIS_PORT    = 6379
DEFAULT_REDIS_CHANNEL = "roboparam:results"
DEFAULT_TOTAL_MSGS    = 500_000
DEFAULT_CLIENT_COUNTS = [1, 5, 10, 50, 100]


# ──────────────────────────────────────────────────────────────────
# Data classes
# ──────────────────────────────────────────────────────────────────
@dataclass
class ClientStats:
    client_id: int
    messages_received: int = 0
    latencies_ms: List[float] = field(default_factory=list)
    connect_time_ms: float = 0.0
    errors: int = 0
    connected: bool = False
    disconnect_reason: str = ""


@dataclass
class RunResult:
    num_clients: int
    messages_sent: int
    duration_s: float
    client_stats: List[ClientStats]

    # ── aggregates ──────────────────────────────────────────────

    @property
    def total_received(self) -> int:
        return sum(s.messages_received for s in self.client_stats)

    @property
    def connected_clients(self) -> int:
        return sum(1 for s in self.client_stats if s.connected)

    @property
    def publish_rate(self) -> float:
        return self.messages_sent / self.duration_s if self.duration_s > 0 else 0.0

    @property
    def receive_rate(self) -> float:
        return self.total_received / self.duration_s if self.duration_s > 0 else 0.0

    @property
    def all_latencies(self) -> List[float]:
        lats: List[float] = []
        for s in self.client_stats:
            lats.extend(s.latencies_ms)
        return sorted(lats)

    def percentile(self, p: float) -> float:
        lats = self.all_latencies
        if not lats:
            return 0.0
        idx = min(int(len(lats) * p / 100), len(lats) - 1)
        return lats[idx]

    @property
    def avg_connect_ms(self) -> float:
        times = [s.connect_time_ms for s in self.client_stats if s.connected]
        return statistics.mean(times) if times else 0.0

    @property
    def total_errors(self) -> int:
        return sum(s.errors for s in self.client_stats)


# ──────────────────────────────────────────────────────────────────
# Message generation
# ──────────────────────────────────────────────────────────────────
_ROBOT_IDS = [f"arm-{i}" for i in range(1, 6)]


def generate_messages(n: int) -> List[dict]:
    """
    Pre-generate n SimResult-shaped dicts.

    Each dict has two extra fields:
      _ts  — epoch-milliseconds (set to 0 here; overwritten at publish time)
      _seq — zero-based sequence number (for debugging dropped messages)

    Joint angles are random values in [-π, π] for the Franka Panda 7-DOF arm.
    """
    print(f"Pre-generating {n:,} messages ...", flush=True)
    t0 = time.perf_counter()
    msgs = []
    for i in range(n):
        msgs.append({
            "deviceId":    _ROBOT_IDS[i % len(_ROBOT_IDS)],
            "module":      "kinematics",
            "jointAngles": [round(random.uniform(-math.pi, math.pi), 4) for _ in range(7)],
            "endEffector": {
                "x": round(random.uniform(-0.5, 0.5), 4),
                "y": round(random.uniform(-0.5, 0.5), 4),
                "z": round(random.uniform(0.10, 0.80), 4),
            },
            "collision": False,
            "latency":   random.randint(5, 50),
            "_ts":  0,   # overwritten just before publish
            "_seq": i,
        })
    elapsed = time.perf_counter() - t0
    print(f"  {n:,} messages ready  ({elapsed:.2f}s, {n / elapsed:,.0f} msg/s)", flush=True)
    return msgs


# ──────────────────────────────────────────────────────────────────
# Async WebSocket client
# ──────────────────────────────────────────────────────────────────
async def ws_client_task(
    client_id: int,
    stats: ClientStats,
    done_event: asyncio.Event,
    ws_url: str,
) -> None:
    """
    Long-lived WebSocket client that receives messages until done_event is set.

    Latency is computed as:
        recv_wall_clock_ms  −  msg["_ts"]
    where _ts was stamped by the Redis publisher immediately before r.publish().
    Both clocks are wall-clock time on the same machine (or close machines),
    so the measurement captures aggregator processing + network delivery time.
    """
    t0 = time.perf_counter()
    try:
        async with websockets.connect(
            ws_url,
            ping_interval=20,
            ping_timeout=10,
            max_size=2 ** 20,          # 1 MiB per message
            open_timeout=10,
        ) as ws:
            stats.connect_time_ms = (time.perf_counter() - t0) * 1000
            stats.connected = True

            while not done_event.is_set():
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
                    recv_ms = time.time() * 1000
                    data = json.loads(raw)
                    ts = data.get("_ts", 0)
                    if ts > 0:
                        lat = recv_ms - ts
                        if 0 < lat < 30_000:          # discard clock-skew outliers
                            stats.latencies_ms.append(lat)
                    stats.messages_received += 1
                except asyncio.TimeoutError:
                    continue
                except json.JSONDecodeError:
                    stats.errors += 1
                except websockets.ConnectionClosed as exc:
                    stats.disconnect_reason = str(exc)
                    break
                except Exception as exc:
                    stats.errors += 1
                    stats.disconnect_reason = str(exc)
                    break

    except Exception as exc:
        stats.connect_time_ms = (time.perf_counter() - t0) * 1000
        stats.disconnect_reason = str(exc)


# ──────────────────────────────────────────────────────────────────
# Redis publisher  (runs in its own thread so asyncio loop stays free)
# ──────────────────────────────────────────────────────────────────
def redis_publisher(
    messages: List[dict],
    redis_host: str,
    redis_port: int,
    channel: str,
    rate_limit: Optional[float],
    ready_event: threading.Event,
    stop_event: threading.Event,
) -> int:
    """
    Publishes all messages to the Redis pub/sub channel.

    Stamps _ts on each message immediately before calling r.publish() so
    the latency measurement is as tight as possible.  Returns the count of
    messages actually sent.
    """
    r = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)
    r.ping()            # fail fast if Redis is unreachable

    delay = (1.0 / rate_limit) if rate_limit else 0.0
    ready_event.set()   # signal: publisher is ready, clients may now start timing

    sent = 0
    for msg in messages:
        if stop_event.is_set():
            break
        msg["_ts"] = time.time() * 1000   # wall-clock stamp in milliseconds
        r.publish(channel, json.dumps(msg))
        sent += 1
        if delay:
            time.sleep(delay)
    return sent


# ──────────────────────────────────────────────────────────────────
# Single test run
# ──────────────────────────────────────────────────────────────────
async def run_one(
    num_clients: int,
    messages: List[dict],
    ws_url: str,
    redis_host: str,
    redis_port: int,
    redis_channel: str,
    rate_limit: Optional[float],
    connect_grace_s: float,
    drain_grace_s: float,
) -> RunResult:
    """
    Steps:
      1. Launch num_clients async WebSocket tasks.
      2. Wait connect_grace_s seconds for connections to stabilize.
      3. Start Redis publisher thread.
      4. Wait for all messages to be published.
      5. Wait drain_grace_s seconds for in-flight messages to arrive.
      6. Signal clients to stop; gather all tasks.
      7. Return aggregated RunResult.
    """
    print(f"\n{'─' * 64}")
    print(f"  Clients: {num_clients:,}   Messages: {len(messages):,}", flush=True)
    print(f"{'─' * 64}", flush=True)

    client_stats = [ClientStats(client_id=i) for i in range(num_clients)]
    done_event = asyncio.Event()

    # ── launch WebSocket clients ─────────────────────────────────
    tasks = [
        asyncio.create_task(ws_client_task(i, client_stats[i], done_event, ws_url))
        for i in range(num_clients)
    ]

    # ── wait for connections ─────────────────────────────────────
    print(f"  Connecting {num_clients} WebSocket clients "
          f"(grace={connect_grace_s}s) ...", end="", flush=True)
    await asyncio.sleep(connect_grace_s)
    connected = sum(1 for s in client_stats if s.connected)
    print(f" {connected}/{num_clients} connected", flush=True)

    if connected == 0:
        failed_reasons = {s.disconnect_reason for s in client_stats if s.disconnect_reason}
        print(f"  ERROR: 0 clients connected.  Check WebSocket server at {ws_url}")
        if failed_reasons:
            print(f"  Errors: {failed_reasons}")
        done_event.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        return RunResult(num_clients=num_clients, messages_sent=0,
                         duration_s=0.0, client_stats=client_stats)

    # ── start Redis publisher in background thread ───────────────
    ready_event  = threading.Event()
    stop_event   = threading.Event()
    sent_count   = [0]

    def _run_publisher():
        sent_count[0] = redis_publisher(
            messages, redis_host, redis_port, redis_channel,
            rate_limit, ready_event, stop_event,
        )

    pub_thread = threading.Thread(target=_run_publisher, daemon=True)
    pub_thread.start()
    ready_event.wait(timeout=5.0)

    print(f"  Publishing {len(messages):,} messages to Redis ...", flush=True)
    t_start = time.perf_counter()
    pub_thread.join()
    duration_s = time.perf_counter() - t_start
    print(f"  Published {sent_count[0]:,} messages in {duration_s:.2f}s "
          f"({sent_count[0]/duration_s:,.0f} msg/s)", flush=True)

    # ── drain period ─────────────────────────────────────────────
    print(f"  Draining in-flight messages (grace={drain_grace_s}s) ...", flush=True)
    await asyncio.sleep(drain_grace_s)

    # ── shut down clients ─────────────────────────────────────────
    done_event.set()
    await asyncio.gather(*tasks, return_exceptions=True)

    return RunResult(
        num_clients=num_clients,
        messages_sent=sent_count[0],
        duration_s=duration_s,
        client_stats=client_stats,
    )


# ──────────────────────────────────────────────────────────────────
# Result printing
# ──────────────────────────────────────────────────────────────────
def print_run_result(r: RunResult) -> None:
    lats = r.all_latencies
    has_lat = bool(lats)

    print(f"\n  Results:")
    print(f"    Messages sent:           {r.messages_sent:>12,}")
    print(f"    Messages received:       {r.total_received:>12,}")
    print(f"    Connected clients:       {r.connected_clients:>12} / {r.num_clients}")

    if r.messages_sent > 0 and r.connected_clients > 0:
        per_client_recv = r.total_received / r.connected_clients
        delivery_pct    = per_client_recv / r.messages_sent * 100
        print(f"    Per-client delivery:     {delivery_pct:>11.1f}%"
              f"  ({per_client_recv:,.0f} / {r.messages_sent:,})")

    print(f"    Publish duration:        {r.duration_s:>11.2f}s")
    print(f"    Publish throughput:      {r.publish_rate:>11,.0f} msg/s")
    print(f"    Receive throughput:      {r.receive_rate:>11,.0f} msg/s  (all clients)")
    print(f"    Avg connect time:        {r.avg_connect_ms:>11.1f} ms")
    print(f"    Total errors:            {r.total_errors:>12,}")

    if has_lat:
        print(f"\n  End-to-end latency  (Redis publish  →  WebSocket receive):")
        print(f"    Samples:   {len(lats):>12,}")
        print(f"    Min:       {min(lats):>11.2f} ms")
        print(f"    Mean:      {statistics.mean(lats):>11.2f} ms")
        print(f"    Std dev:   {statistics.stdev(lats):>11.2f} ms")
        print(f"    p50:       {r.percentile(50):>11.2f} ms")
        print(f"    p75:       {r.percentile(75):>11.2f} ms")
        print(f"    p95:       {r.percentile(95):>11.2f} ms")
        print(f"    p99:       {r.percentile(99):>11.2f} ms")
        print(f"    p99.9:     {r.percentile(99.9):>11.2f} ms")
        print(f"    Max:       {max(lats):>11.2f} ms")
    else:
        print(f"\n  (no latency samples collected)")


def print_summary(results: List[RunResult]) -> None:
    print(f"\n{'═' * 82}")
    print("BENCHMARK SUMMARY")
    print(f"{'═' * 82}")
    hdr = (f"{'Clients':>8}  {'Sent':>10}  {'Rcvd':>10}  "
           f"{'Del%':>6}  {'Pub/s':>9}  "
           f"{'p50ms':>7}  {'p95ms':>7}  {'p99ms':>7}  {'Errs':>6}")
    print(hdr)
    print("─" * 82)
    for r in results:
        lats = r.all_latencies
        p50  = r.percentile(50)  if lats else 0.0
        p95  = r.percentile(95)  if lats else 0.0
        p99  = r.percentile(99)  if lats else 0.0
        del_pct = (
            r.total_received / (r.messages_sent * r.connected_clients) * 100
            if r.messages_sent > 0 and r.connected_clients > 0 else 0.0
        )
        print(f"{r.num_clients:>8,}  {r.messages_sent:>10,}  {r.total_received:>10,}  "
              f"{del_pct:>5.1f}%  {r.publish_rate:>9,.0f}  "
              f"{p50:>7.1f}  {p95:>7.1f}  {p99:>7.1f}  {r.total_errors:>6,}")


def analyze_bottlenecks(results: List[RunResult]) -> None:
    """
    Reads across all RunResult objects and prints a plain-English bottleneck
    analysis.  Checks five independent signals:

      1. Broadcast-thread saturation  — p99 latency grows faster than linearly
                                        with client count (single-threaded loop
                                        in WebSocketHandler.broadcast())
      2. Delivery degradation         — per-client delivery % drops below 99 %,
                                        indicating send-buffer backpressure
      3. Connection failures          — fewer clients connected than requested,
                                        pointing to OS fd limits or server thread
                                        pool exhaustion
      4. Error rate                   — errors > 1 % of messages received
      5. Latency knee                 — the exact client count where p99 first
                                        exceeds 2× the single-client baseline
    """
    valid = [r for r in results if r.messages_sent > 0 and r.connected_clients > 0]
    if not valid:
        return

    print(f"\n{'═' * 82}")
    print("BOTTLENECK ANALYSIS")
    print(f"{'═' * 82}")

    findings: List[str] = []
    warnings: List[str] = []

    # ── baseline (lowest client count) ───────────────────────────
    baseline = valid[0]
    baseline_p99  = baseline.percentile(99)
    baseline_p50  = baseline.percentile(50)
    baseline_rate = baseline.publish_rate

    # ── 1. broadcast-thread saturation ───────────────────────────
    if len(valid) >= 2:
        # Build (clients, p99) pairs for runs that have latency data
        lat_series = [(r.num_clients, r.percentile(99))
                      for r in valid if r.all_latencies]
        if len(lat_series) >= 2:
            # Expected latency if it scaled linearly with client count
            c0, p0 = lat_series[0]
            degradation_detected = False
            knee_clients = None
            for c, p in lat_series[1:]:
                linear_expected = p0 * (c / c0)
                if p > linear_expected * 1.5:          # 50 % worse than linear
                    degradation_detected = True
                    if knee_clients is None:
                        knee_clients = c
            if degradation_detected:
                findings.append(
                    f"[BROADCAST THREAD]  p99 latency grows super-linearly — "
                    f"WebSocketHandler.broadcast() is a single-threaded loop "
                    f"that blocks on each session.sendMessage() call.  "
                    f"Degradation visible from {knee_clients} clients onward.\n"
                    f"    Fix: run broadcast() in a thread pool, or replace "
                    f"CopyOnWriteArraySet iteration with per-session async writes."
                )
            else:
                warnings.append(
                    "[OK] p99 latency scales roughly linearly — "
                    "broadcast thread is not yet saturated at these client counts."
                )

    # ── 2. delivery degradation ───────────────────────────────────
    degraded_at = None
    for r in valid:
        if r.messages_sent > 0 and r.connected_clients > 0:
            per_client_pct = (
                (r.total_received / r.connected_clients) / r.messages_sent * 100
            )
            if per_client_pct < 99.0 and degraded_at is None:
                degraded_at = (r.num_clients, per_client_pct)

    if degraded_at:
        nc, pct = degraded_at
        findings.append(
            f"[DELIVERY LOSS]  Per-client delivery dropped to {pct:.1f}% at "
            f"{nc} clients — the server is dropping messages before they reach "
            f"clients.  Likely cause: slow clients fill their TCP send buffer; "
            f"Spring's sendMessage() blocks, causing the broadcast loop to fall "
            f"behind the Redis publish rate.\n"
            f"    Fix: add a per-session send queue with a bounded drop policy, "
            f"or throttle the publish rate (--rate flag)."
        )
    else:
        warnings.append("[OK] Per-client delivery ≥ 99% across all runs — no message loss detected.")

    # ── 3. connection failures ────────────────────────────────────
    conn_failures = [(r.num_clients, r.connected_clients)
                     for r in valid if r.connected_clients < r.num_clients]
    if conn_failures:
        worst_nc, worst_conn = max(conn_failures, key=lambda x: x[0] - x[1])
        findings.append(
            f"[CONNECTION LIMIT]  Only {worst_conn}/{worst_nc} clients "
            f"connected successfully.  Possible causes:\n"
            f"    • OS file-descriptor limit (check: ulimit -n; fix: ulimit -n 65535)\n"
            f"    • Spring WebSocket thread pool exhausted — increase "
            f"server.tomcat.threads.max in application.properties\n"
            f"    • TCP port exhaustion on the client side"
        )
    else:
        warnings.append("[OK] All requested clients connected successfully — no fd/thread-pool limit hit.")

    # ── 4. error rate ─────────────────────────────────────────────
    for r in valid:
        if r.total_received > 0:
            err_pct = r.total_errors / r.total_received * 100
            if err_pct > 1.0:
                findings.append(
                    f"[HIGH ERROR RATE]  {r.total_errors:,} errors at {r.num_clients} clients "
                    f"({err_pct:.1f}% of received messages).  Inspect client disconnect reasons — "
                    f"likely server-side WebSocket frame errors or connection resets under load."
                )

    # ── 5. latency knee ───────────────────────────────────────────
    if baseline_p99 > 0 and len(valid) >= 2:
        knee = next(
            (r.num_clients for r in valid[1:]
             if r.all_latencies and r.percentile(99) > baseline_p99 * 2),
            None,
        )
        if knee:
            warnings.append(
                f"[LATENCY KNEE]  p99 latency first exceeds 2× baseline at "
                f"{knee} clients (baseline p99={baseline_p99:.1f} ms).  "
                f"This is the practical concurrency limit before noticeable "
                f"tail-latency impact."
            )

    # ── 6. publish rate stability ─────────────────────────────────
    if len(valid) >= 2 and baseline_rate > 0:
        rates = [r.publish_rate for r in valid]
        rate_drop = (max(rates) - min(rates)) / max(rates) * 100
        if rate_drop > 20:
            findings.append(
                f"[REDIS BOTTLENECK]  Publish rate varied by {rate_drop:.0f}% "
                f"across runs ({min(rates):,.0f}–{max(rates):,.0f} msg/s).  "
                f"Redis may be under memory or CPU pressure at higher client counts."
            )
        else:
            warnings.append(
                f"[OK] Publish rate stable across runs "
                f"({min(rates):,.0f}–{max(rates):,.0f} msg/s) — Redis is not the bottleneck."
            )

    # ── print results ─────────────────────────────────────────────
    if findings:
        print(f"\n  {'─'*38}  PROBLEMS  {'─'*31}")
        for i, f in enumerate(findings, 1):
            # Indent continuation lines
            lines = f.split("\n")
            print(f"\n  {i}. {lines[0]}")
            for line in lines[1:]:
                print(f"     {line}")
    else:
        print("\n  No significant bottlenecks detected at the tested concurrency levels.")

    if warnings:
        print(f"\n  {'─'*40}  INFO  {'─'*33}")
        for w in warnings:
            print(f"  • {w}")

    print()


def write_csv(results: List[RunResult], path: str) -> None:
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "clients", "messages_sent", "messages_received",
            "connected_clients", "duration_s",
            "publish_rate_msg_s", "receive_rate_msg_s",
            "avg_connect_ms",
            "lat_samples",
            "lat_min_ms", "lat_mean_ms", "lat_stdev_ms",
            "lat_p50_ms",  "lat_p75_ms",
            "lat_p95_ms",  "lat_p99_ms", "lat_p999_ms",
            "lat_max_ms",
            "total_errors",
        ])
        for r in results:
            lats = r.all_latencies
            writer.writerow([
                r.num_clients,
                r.messages_sent,
                r.total_received,
                r.connected_clients,
                f"{r.duration_s:.3f}",
                f"{r.publish_rate:.1f}",
                f"{r.receive_rate:.1f}",
                f"{r.avg_connect_ms:.2f}",
                len(lats),
                f"{min(lats):.2f}"              if lats else "",
                f"{statistics.mean(lats):.2f}"  if lats else "",
                f"{statistics.stdev(lats):.2f}" if len(lats) > 1 else "",
                f"{r.percentile(50):.2f}"       if lats else "",
                f"{r.percentile(75):.2f}"       if lats else "",
                f"{r.percentile(95):.2f}"       if lats else "",
                f"{r.percentile(99):.2f}"       if lats else "",
                f"{r.percentile(99.9):.2f}"     if lats else "",
                f"{max(lats):.2f}"              if lats else "",
                r.total_errors,
            ])
    print(f"\nResults written to: {path}")


# ──────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────
async def async_main(args: argparse.Namespace) -> None:
    # ── sanity-check Redis connectivity before generating messages ──
    try:
        r = redis.Redis(host=args.redis_host, port=args.redis_port)
        r.ping()
        print(f"Redis OK  ({args.redis_host}:{args.redis_port})", flush=True)
    except Exception as exc:
        print(f"ERROR: Cannot reach Redis at {args.redis_host}:{args.redis_port}: {exc}")
        sys.exit(1)

    messages     = generate_messages(args.messages)
    client_counts = sorted(set(args.clients))

    all_results: List[RunResult] = []
    for nc in client_counts:
        result = await run_one(
            num_clients    = nc,
            messages       = messages,
            ws_url         = args.ws_url,
            redis_host     = args.redis_host,
            redis_port     = args.redis_port,
            redis_channel  = args.redis_channel,
            rate_limit     = args.rate,
            connect_grace_s = args.connect_grace,
            drain_grace_s   = args.drain_grace,
        )
        print_run_result(result)
        all_results.append(result)

    print_summary(all_results)
    analyze_bottlenecks(all_results)

    if args.output:
        write_csv(all_results, args.output)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stress test the RoboParam WebSocket aggregator.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--ws-url", default=DEFAULT_WS_URL,
        help="WebSocket URL of the aggregator",
    )
    parser.add_argument(
        "--redis-host", default=DEFAULT_REDIS_HOST,
        help="Redis host",
    )
    parser.add_argument(
        "--redis-port", type=int, default=DEFAULT_REDIS_PORT,
        help="Redis port",
    )
    parser.add_argument(
        "--redis-channel", default=DEFAULT_REDIS_CHANNEL,
        help="Redis pub/sub channel",
    )
    parser.add_argument(
        "--messages", type=int, default=DEFAULT_TOTAL_MSGS,
        metavar="N",
        help="Messages to pre-generate and send per run",
    )
    parser.add_argument(
        "--clients", type=int, nargs="+", default=DEFAULT_CLIENT_COUNTS,
        metavar="N",
        help="Concurrent WebSocket client counts to benchmark (space-separated)",
    )
    parser.add_argument(
        "--rate", type=float, default=None,
        metavar="MSG/S",
        help="Max Redis publish rate in msg/s (default: unlimited)",
    )
    parser.add_argument(
        "--connect-grace", type=float, default=3.0,
        metavar="S",
        help="Seconds to wait for clients to connect before publishing",
    )
    parser.add_argument(
        "--drain-grace", type=float, default=3.0,
        metavar="S",
        help="Seconds to wait after publishing before collecting results",
    )
    parser.add_argument(
        "--output", default=None,
        metavar="FILE.csv",
        help="Write benchmark results to a CSV file",
    )

    args = parser.parse_args()
    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
