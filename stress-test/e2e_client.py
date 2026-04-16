#!/usr/bin/env python3
"""
End-to-End Round-Trip Client

Simulates N independent clients, each with its own WebSocket connection to the
aggregator and its own SQS sender thread:

    Client-0  ──→  SQS ──→  worker3 ──→  Isaac Sim ──→  worker3 ──→  Redis ──→  Aggregator ──→  Client-0
    Client-1  ──→  SQS ──────────────────────────────────────────────────────────────────────→  Client-1
    ...

Each Client object owns:
  - A unique deviceId  (stress-arm-0, stress-arm-1, ...)
  - A pre-generated sinusoidal joint-angle trajectory
  - One boto3 SQS client  (blocking, runs in a sub-thread)
  - One WebSocket connection to the aggregator  (async, runs in the client thread)
  - A per-client deque of send timestamps for latency matching

Latency matching
----------------
No correlation ID survives the pipeline — worker3 strips every field except
deviceId, jointAngles, endEffector, collision, and latency.  Each client
matches incoming SimResults by deviceId and pairs them with the oldest
unmatched send timestamp in its own deque.

Because the aggregator broadcasts to ALL connected clients, each client
receives SimResults for every deviceId, not just its own.  Messages whose
deviceId does not match the client's own deviceId are counted as
unmatched_receives and their latency is not recorded (they came from another
client's sends, not this one's).

Usage
-----
  # Smoke test — 1 client, 100 messages, rate-limited to 5 msg/s
  python e2e_client.py --threads 1 --messages 100 --rate 5

  # Sweep concurrency levels
  python e2e_client.py --threads 1 2 4 8 --messages 500000

  # Save results
  python e2e_client.py --threads 1 4 8 --output e2e_results.csv

Requirements
------------
  pip install boto3 websockets
  AWS credentials configured  (aws configure or environment variables)
  Python >= 3.9
"""

import argparse
import asyncio
import collections
import csv
import json
import math
import statistics
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Deque, List, Optional

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:
    print("Missing dependency: boto3\n  pip install boto3")
    sys.exit(1)

try:
    import websockets
except ImportError:
    print("Missing dependency: websockets\n  pip install websockets")
    sys.exit(1)


# ──────────────────────────────────────────────────────────────────
# Defaults
# ──────────────────────────────────────────────────────────────────
DEFAULT_QUEUE_URL  = "https://sqs.us-east-1.amazonaws.com/179895363911/roboparam-queue"
DEFAULT_REGION     = "us-east-1"
DEFAULT_WS_URL     = "ws://localhost:8082/ws/results"
DEFAULT_TOTAL_MSGS = 500_000
DEFAULT_THREADS    = [1, 2, 4, 8]

# Franka Panda joint limits (radians) — from vla/VLA_EC2_SETUP.md
JOINT_LIMITS = [
    (-2.8973,  2.8973),
    (-1.7628,  1.7628),
    (-2.8973,  2.8973),
    (-3.0718, -0.0698),
    (-2.8973,  2.8973),
    (-0.0175,  3.7525),
    (-2.8973,  2.8973),
]
HOME_ANGLES = [0.0, -0.785, 0.0, -2.356, 0.0, 1.571, 0.785]


# ──────────────────────────────────────────────────────────────────
# Trajectory generation
# ──────────────────────────────────────────────────────────────────
def generate_trajectory(n: int, thread_id: int) -> List[List[float]]:
    """
    Returns n joint-angle arrays as a smooth sinusoidal trajectory within
    Franka joint limits.  thread_id shifts the frequency so concurrent
    clients don't produce identical commands.
    """
    freq_base = 1.0 + thread_id * 0.07
    result = []
    for i in range(n):
        angles = []
        for j, (lo, hi) in enumerate(JOINT_LIMITS):
            mid = HOME_ANGLES[j]
            amp = min((hi - lo) * 0.25, mid - lo, hi - mid)
            freq = freq_base * (0.8 + j * 0.05)
            a = mid + amp * math.sin(2 * math.pi * freq * i / max(n, 1))
            angles.append(round(a, 4))
        result.append(angles)
    return result


# ──────────────────────────────────────────────────────────────────
# Per-client stats
# ──────────────────────────────────────────────────────────────────
@dataclass
class ClientStats:
    client_id: int
    device_id: str
    # sender
    messages_sent: int = 0
    send_errors: int = 0
    send_start: float = 0.0
    send_end: float = 0.0
    # receiver
    messages_received: int = 0
    unmatched_receives: int = 0        # SimResults for other deviceIds
    round_trip_latencies_ms: List[float] = field(default_factory=list)
    pipeline_latencies_ms: List[float] = field(default_factory=list)
    ws_connected: bool = False
    recv_start: float = 0.0
    recv_end: float = 0.0

    @property
    def send_duration_s(self) -> float:
        return self.send_end - self.send_start if self.send_end > self.send_start else 0.0

    @property
    def send_rate(self) -> float:
        return self.messages_sent / self.send_duration_s if self.send_duration_s > 0 else 0.0

    @property
    def recv_duration_s(self) -> float:
        return self.recv_end - self.recv_start if self.recv_end > self.recv_start else 0.0

    @property
    def recv_rate(self) -> float:
        return self.messages_received / self.recv_duration_s if self.recv_duration_s > 0 else 0.0

    def percentile(self, lats: List[float], p: float) -> float:
        if not lats:
            return 0.0
        s = sorted(lats)
        return s[min(int(len(s) * p / 100), len(s) - 1)]


# ──────────────────────────────────────────────────────────────────
# Client: one sender sub-thread + one WebSocket connection
# ──────────────────────────────────────────────────────────────────
class Client:
    """
    One simulated end-to-end client.

    Thread model
    ────────────
    run() is called from an OS thread (one per client).  Inside run(), an
    asyncio event loop drives the WebSocket receiver coroutine.  A further
    sub-thread inside run() drives the blocking SQS sender so it does not
    block the asyncio loop.

                OS thread (client N)
                ├── asyncio loop  ──→  WebSocket receiver coroutine
                └── sub-thread    ──→  SQS sender (blocking boto3 calls)

    The two sides communicate through self._pending, a collections.deque.
    deque.append() and deque.popleft() are atomic in CPython, so no lock
    is needed for this single-producer / single-consumer pattern.
    """

    def __init__(
        self,
        client_id: int,
        trajectory: List[List[float]],
        queue_url: str,
        region: str,
        rate_limit: Optional[float],
        ws_url: str,
    ) -> None:
        self.client_id  = client_id
        self.device_id  = f"stress-arm-{client_id}"
        self.trajectory = trajectory
        self.queue_url  = queue_url
        self.region     = region
        self.rate_limit = rate_limit
        self.ws_url     = ws_url

        self.stats: ClientStats = ClientStats(
            client_id=client_id, device_id=self.device_id
        )

        # Timestamps of sends that have not yet been matched to a SimResult.
        # Appended by the SQS sub-thread; popped by the receiver coroutine.
        self._pending: Deque[float] = collections.deque()

        # Set by run_one after the drain period to stop the receiver loop.
        self._stop: threading.Event = threading.Event()

        # Set by the SQS sub-thread when it has sent its last message.
        self._sender_done: threading.Event = threading.Event()

    # ── public interface ──────────────────────────────────────────

    def run(self) -> None:
        """Entry point for this client's OS thread."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._run_async())
        finally:
            loop.close()

    def stop(self) -> None:
        """Signal the receiver loop to exit (called by run_one after drain)."""
        self._stop.set()

    @property
    def sender_done(self) -> bool:
        return self._sender_done.is_set()

    # ── async receiver ────────────────────────────────────────────

    async def _run_async(self) -> None:
        """
        Opens the WebSocket connection, then starts the SQS sender in a
        sub-thread and runs the receiver loop until self._stop is set.
        """
        try:
            async with websockets.connect(
                self.ws_url,
                ping_interval=20,
                ping_timeout=10,
                max_size=2 ** 20,
                open_timeout=10,
            ) as ws:
                self.stats.ws_connected = True
                self.stats.recv_start = time.time()

                # Start the SQS sender sub-thread now that the WebSocket is open
                sender = threading.Thread(target=self._send_loop, daemon=True)
                sender.start()

                await self._recv_loop(ws)

                sender.join()
                self.stats.recv_end = time.time()

        except Exception as exc:
            self.stats.recv_end = time.time()
            print(f"  [client-{self.client_id}] WebSocket error: {exc}", flush=True)

    async def _recv_loop(self, ws) -> None:
        """
        Receives SimResult messages until self._stop is set.

        For each message:
          - If deviceId matches this client → match against oldest pending
            send timestamp → compute round-trip latency
          - Always record SimResult.latency (worker3's Isaac Sim call time)
          - Count messages for other deviceIds as unmatched_receives
        """
        while not self._stop.is_set():
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            except websockets.ConnectionClosed as exc:
                print(f"  [client-{self.client_id}] WebSocket closed: {exc}",
                      flush=True)
                break

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            self.stats.messages_received += 1

            # Match by deviceId — only this client's own SimResults count
            if data.get("deviceId") == self.device_id and self._pending:
                send_ts = self._pending.popleft()
                rtt = time.time() * 1000 - send_ts
                if 0 < rtt < 120_000:
                    self.stats.round_trip_latencies_ms.append(rtt)
            else:
                self.stats.unmatched_receives += 1

            # Always collect Isaac Sim latency from SimResult.latency
            pip_lat = data.get("latency")
            if isinstance(pip_lat, (int, float)) and pip_lat > 0:
                self.stats.pipeline_latencies_ms.append(float(pip_lat))

    # ── SQS sender (runs in sub-thread) ──────────────────────────

    def _send_loop(self) -> None:
        """
        Publishes every joint-angle step in self.trajectory to SQS.
        Runs in a dedicated sub-thread so blocking boto3 calls don't
        stall the asyncio event loop that drives the WebSocket receiver.
        """
        sqs   = boto3.client("sqs", region_name=self.region)
        delay = (1.0 / self.rate_limit) if self.rate_limit else 0.0

        self.stats.send_start = time.perf_counter()

        for angles in self.trajectory:
            body = json.dumps({
                "robotId":     self.device_id,
                "deviceId":    self.device_id,
                "serverId":    f"e2e-server-{self.client_id}",
                "clientId":    f"e2e-client-{self.client_id}",
                "jointAngles": angles,
                "timestamp":   datetime.now(timezone.utc).isoformat(),
            })

            # Record send timestamp BEFORE the network call so latency
            # includes SQS enqueue time, not just post-send wall time.
            self._pending.append(time.time() * 1000)

            try:
                sqs.send_message(QueueUrl=self.queue_url, MessageBody=body)
                self.stats.messages_sent += 1
            except (BotoCoreError, ClientError) as exc:
                self._pending.pop()   # discard the timestamp for this failed send
                self.stats.send_errors += 1
                if self.stats.send_errors <= 5:
                    print(f"  [client-{self.client_id}] SQS error: {exc}",
                          flush=True)

            if delay:
                time.sleep(delay)

        self.stats.send_end = time.perf_counter()
        self._sender_done.set()


# ──────────────────────────────────────────────────────────────────
# RunResult
# ──────────────────────────────────────────────────────────────────
@dataclass
class RunResult:
    num_clients: int
    client_stats: List[ClientStats]

    @property
    def total_sent(self) -> int:
        return sum(s.messages_sent for s in self.client_stats)

    @property
    def total_received(self) -> int:
        return sum(s.messages_received for s in self.client_stats)

    @property
    def total_errors(self) -> int:
        return sum(s.send_errors for s in self.client_stats)

    @property
    def connected_clients(self) -> int:
        return sum(1 for s in self.client_stats if s.ws_connected)

    @property
    def wall_duration_s(self) -> float:
        starts = [s.send_start for s in self.client_stats if s.send_start > 0]
        ends   = [s.send_end   for s in self.client_stats if s.send_end   > 0]
        return (max(ends) - min(starts)) if starts and ends else 0.0

    @property
    def total_send_rate(self) -> float:
        d = self.wall_duration_s
        return self.total_sent / d if d > 0 else 0.0

    @property
    def all_rtts(self) -> List[float]:
        lats: List[float] = []
        for s in self.client_stats:
            lats.extend(s.round_trip_latencies_ms)
        return sorted(lats)

    @property
    def all_pipeline_lats(self) -> List[float]:
        lats: List[float] = []
        for s in self.client_stats:
            lats.extend(s.pipeline_latencies_ms)
        return sorted(lats)

    def percentile(self, lats: List[float], p: float) -> float:
        if not lats:
            return 0.0
        return lats[min(int(len(lats) * p / 100), len(lats) - 1)]


# ──────────────────────────────────────────────────────────────────
# Single test run
# ──────────────────────────────────────────────────────────────────
def run_one(
    num_clients: int,
    trajectories: List[List[List[float]]],
    queue_url: str,
    region: str,
    rate_limit: Optional[float],
    ws_url: str,
    drain_grace_s: float,
) -> RunResult:
    msgs_per_client = len(trajectories[0])

    print(f"\n{'─' * 64}")
    print(f"  Clients: {num_clients}   "
          f"Messages/client: {msgs_per_client:,}   "
          f"Total: {num_clients * msgs_per_client:,}", flush=True)
    print(f"{'─' * 64}", flush=True)

    # Create one Client object per simulated user
    clients = [
        Client(
            client_id  = i,
            trajectory = trajectories[i],
            queue_url  = queue_url,
            region     = region,
            rate_limit = rate_limit,
            ws_url     = ws_url,
        )
        for i in range(num_clients)
    ]

    # Each Client runs in its own OS thread
    threads = [threading.Thread(target=c.run, daemon=True) for c in clients]
    for t in threads:
        t.start()

    # Give WebSocket connections time to open before progress reporting
    time.sleep(1.5)
    connected = sum(1 for c in clients if c.stats.ws_connected)
    print(f"  WebSocket connections: {connected}/{num_clients}", flush=True)

    # Progress reporter
    def _progress():
        while not all(c.sender_done for c in clients):
            sent  = sum(c.stats.messages_sent   for c in clients)
            rcvd  = sum(c.stats.messages_received for c in clients)
            backlog = sum(len(c._pending) for c in clients)
            print(f"  ... sent={sent:,}  received={rcvd:,}  "
                  f"pipeline_backlog≈{backlog:,}", flush=True)
            time.sleep(5.0)

    threading.Thread(target=_progress, daemon=True).start()

    # Wait for all senders to finish
    for c in clients:
        c._sender_done.wait()

    total_sent = sum(c.stats.messages_sent for c in clients)
    print(f"  All senders done ({total_sent:,} messages sent).  "
          f"Draining pipeline ({drain_grace_s}s) ...", flush=True)

    # Drain: let the pipeline process the remaining SQS backlog
    time.sleep(drain_grace_s)

    # Stop all receiver loops and wait for threads to exit
    for c in clients:
        c.stop()
    for t in threads:
        t.join(timeout=5.0)

    return RunResult(
        num_clients  = num_clients,
        client_stats = [c.stats for c in clients],
    )


# ──────────────────────────────────────────────────────────────────
# Output
# ──────────────────────────────────────────────────────────────────
def print_run_result(r: RunResult) -> None:
    rtts  = r.all_rtts
    plats = r.all_pipeline_lats

    print(f"\n  Results:")
    print(f"    Clients:                  {r.num_clients:>11}")
    print(f"    WS connected:             {r.connected_clients:>11}")

    print(f"\n  Send  (Client → SQS):")
    print(f"    Messages sent:            {r.total_sent:>11,}")
    print(f"    SQS errors:               {r.total_errors:>11,}")
    print(f"    Wall duration:            {r.wall_duration_s:>10.2f}s")
    print(f"    Total send rate:          {r.total_send_rate:>10,.0f} msg/s")
    rates = [s.send_rate for s in r.client_stats if s.messages_sent > 0]
    if rates:
        print(f"    Per-client send rate:     "
              f"{min(rates):,.0f}–{max(rates):,.0f} msg/s")

    print(f"\n  Receive  (Aggregator → Client):")
    print(f"    Messages received:        {r.total_received:>11,}")
    unmatched = sum(s.unmatched_receives for s in r.client_stats)
    print(f"    Unmatched receives:       {unmatched:>11,}  "
          f"(SimResults for other deviceIds)")
    if r.total_sent > 0:
        matched = len(rtts)
        print(f"    Matched (own deviceId):   {matched:>11,}")
        print(f"    Delivery rate:            {matched / r.total_sent * 100:>10.1f}%")

    if rtts:
        print(f"\n  Round-trip latency  (SQS send → WebSocket receive):")
        print(f"    Samples:    {len(rtts):>11,}")
        print(f"    Min:        {min(rtts):>10.0f} ms")
        print(f"    Mean:       {statistics.mean(rtts):>10.0f} ms")
        print(f"    p50:        {r.percentile(rtts, 50):>10.0f} ms")
        print(f"    p75:        {r.percentile(rtts, 75):>10.0f} ms")
        print(f"    p95:        {r.percentile(rtts, 95):>10.0f} ms")
        print(f"    p99:        {r.percentile(rtts, 99):>10.0f} ms")
        print(f"    Max:        {max(rtts):>10.0f} ms")
    else:
        print(f"\n  (no round-trip latency samples — "
              f"check that deviceIds match and drain-grace is long enough)")

    if plats:
        print(f"\n  Isaac Sim latency  (from SimResult.latency, set by worker3):")
        print(f"    Samples:    {len(plats):>11,}")
        print(f"    Min:        {min(plats):>10.0f} ms")
        print(f"    Mean:       {statistics.mean(plats):>10.0f} ms")
        print(f"    p50:        {r.percentile(plats, 50):>10.0f} ms")
        print(f"    p95:        {r.percentile(plats, 95):>10.0f} ms")
        print(f"    p99:        {r.percentile(plats, 99):>10.0f} ms")
        print(f"    Max:        {max(plats):>10.0f} ms")

    if rtts and plats and len(rtts) >= 10 and len(plats) >= 10:
        rtt_mean = statistics.mean(rtts)
        pip_mean = statistics.mean(plats)
        overhead = rtt_mean - pip_mean
        print(f"\n  Latency breakdown (approximate means):")
        print(f"    Total round-trip:         {rtt_mean:>10.0f} ms  (100%)")
        print(f"    Isaac Sim (worker3):      {pip_mean:>10.0f} ms  "
              f"({pip_mean / rtt_mean * 100:.0f}%)")
        print(f"    SQS + Redis + WebSocket:  {overhead:>10.0f} ms  "
              f"({overhead / rtt_mean * 100:.0f}%)")


def print_summary(results: List[RunResult]) -> None:
    print(f"\n{'═' * 90}")
    print("BENCHMARK SUMMARY")
    print(f"{'═' * 90}")
    hdr = (f"{'Clients':>8}  {'Sent':>10}  {'Matched':>9}  {'Del%':>6}  "
           f"{'Send/s':>8}  {'RTT p50':>9}  {'RTT p99':>9}  {'Isaac p50':>10}")
    print(hdr)
    print("─" * 90)
    for r in results:
        rtts  = r.all_rtts
        plats = r.all_pipeline_lats
        matched = len(rtts)
        del_pct = matched / r.total_sent * 100 if r.total_sent > 0 else 0
        print(f"{r.num_clients:>8}  {r.total_sent:>10,}  {matched:>9,}  "
              f"{del_pct:>5.1f}%  {r.total_send_rate:>8,.0f}  "
              f"{r.percentile(rtts, 50):>9.0f}  {r.percentile(rtts, 99):>9.0f}  "
              f"{r.percentile(plats, 50):>10.0f}")


def analyze_bottlenecks(results: List[RunResult]) -> None:
    valid = [r for r in results if r.total_sent > 0]
    if not valid:
        return

    print(f"\n{'═' * 90}")
    print("BOTTLENECK ANALYSIS")
    print(f"{'═' * 90}")

    findings: List[str] = []
    warnings: List[str] = []

    # ── 1. Pipeline ceiling ───────────────────────────────────────
    for r in valid:
        matched   = len(r.all_rtts)
        send_rate = r.total_send_rate
        recv_rate = matched / r.wall_duration_s if r.wall_duration_s > 0 else 0
        if recv_rate > 0 and recv_rate < send_rate * 0.5:
            findings.append(
                f"[PIPELINE CEILING]  Matched receive rate ({recv_rate:.1f} msg/s) is "
                f"less than half the send rate ({send_rate:.0f} msg/s) at "
                f"{r.num_clients} clients.\n"
                f"    worker3 polls up to 5 messages every 500ms → ~10 msg/s max.\n"
                f"    Isaac Sim processes one joint update per HTTP call (synchronous).\n"
                f"    Fix: run multiple worker3 instances, or batch Isaac Sim calls."
            )
            break

    # ── 2. RTT growth with client count ──────────────────────────
    if len(valid) >= 2:
        rtt_series = [
            (r.num_clients, r.percentile(r.all_rtts, 99))
            for r in valid if r.all_rtts
        ]
        if len(rtt_series) >= 2:
            c0, p0 = rtt_series[0]
            knee = next(
                (c for c, p in rtt_series[1:] if p > p0 * 2), None
            )
            if knee:
                findings.append(
                    f"[LATENCY GROWTH]  Round-trip p99 more than doubled from "
                    f"{p0:.0f}ms (1 client) — visible from {knee} clients onward.\n"
                    f"    SQS queue depth is growing: messages wait longer for "
                    f"worker3 to pick them up."
                )
            else:
                warnings.append(
                    "[OK] Round-trip p99 did not double across tested client counts."
                )

    # ── 3. Connection failures ────────────────────────────────────
    for r in valid:
        if r.connected_clients < r.num_clients:
            findings.append(
                f"[CONNECTION FAILURE]  Only {r.connected_clients}/{r.num_clients} "
                f"clients connected at {r.num_clients} clients.\n"
                f"    Check OS file-descriptor limit (ulimit -n) and "
                f"Spring's server.tomcat.threads.max."
            )

    # ── 4. Low delivery ───────────────────────────────────────────
    for r in valid:
        matched = len(r.all_rtts)
        if r.total_sent > 0 and matched / r.total_sent < 0.8:
            findings.append(
                f"[LOW DELIVERY]  Only {matched / r.total_sent * 100:.1f}% of sent "
                f"messages matched a SimResult at {r.num_clients} clients.\n"
                f"    Likely cause: messages still queued in SQS — increase "
                f"--drain-grace (currently worker3 processes ~10 msg/s)."
            )
            break

    # ── 5. Isaac Sim dominance ────────────────────────────────────
    for r in valid:
        rtts  = r.all_rtts
        plats = r.all_pipeline_lats
        if len(rtts) >= 10 and len(plats) >= 10:
            rtt_mean = statistics.mean(rtts)
            pip_mean = statistics.mean(plats)
            if rtt_mean > 0 and pip_mean / rtt_mean > 0.8:
                warnings.append(
                    f"[ISAAC SIM DOMINANT]  Isaac Sim accounts for "
                    f"{pip_mean / rtt_mean * 100:.0f}% of round-trip latency "
                    f"({pip_mean:.0f}ms of {rtt_mean:.0f}ms) — the physics "
                    f"simulation is the primary cost, not the messaging stack."
                )
            break

    # ── 6. SQS errors ────────────────────────────────────────────
    for r in valid:
        attempts = r.total_sent + r.total_errors
        if attempts > 0 and r.total_errors / attempts > 0.01:
            findings.append(
                f"[SQS ERRORS]  {r.total_errors:,} send failures at "
                f"{r.num_clients} clients — check AWS credentials and IAM permissions."
            )

    if findings:
        print(f"\n  {'─'*38}  PROBLEMS  {'─'*31}")
        for i, f in enumerate(findings, 1):
            lines = f.split("\n")
            print(f"\n  {i}. {lines[0]}")
            for line in lines[1:]:
                print(f"     {line}")
    else:
        print("\n  No significant bottlenecks detected at the tested client counts.")

    if warnings:
        print(f"\n  {'─'*40}  INFO  {'─'*33}")
        for w in warnings:
            print(f"  • {w}")

    print()


def write_csv(results: List[RunResult], path: str) -> None:
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "clients", "messages_sent", "matched_received", "sqs_errors",
            "wall_duration_s", "send_rate_msg_s", "delivery_pct",
            "rtt_samples", "rtt_min_ms", "rtt_mean_ms",
            "rtt_p50_ms", "rtt_p75_ms", "rtt_p95_ms", "rtt_p99_ms", "rtt_max_ms",
            "isaac_samples", "isaac_mean_ms", "isaac_p50_ms", "isaac_p99_ms",
        ])
        for r in results:
            rtts  = r.all_rtts
            plats = r.all_pipeline_lats

            def p(lats, pct):
                return f"{r.percentile(lats, pct):.1f}" if lats else ""

            del_pct = len(rtts) / r.total_sent * 100 if r.total_sent > 0 else 0
            writer.writerow([
                r.num_clients, r.total_sent, len(rtts), r.total_errors,
                f"{r.wall_duration_s:.3f}", f"{r.total_send_rate:.1f}",
                f"{del_pct:.1f}",
                len(rtts),
                f"{min(rtts):.1f}"              if rtts else "",
                f"{statistics.mean(rtts):.1f}"  if rtts else "",
                p(rtts, 50), p(rtts, 75), p(rtts, 95), p(rtts, 99),
                f"{max(rtts):.1f}"              if rtts else "",
                len(plats),
                f"{statistics.mean(plats):.1f}" if plats else "",
                p(plats, 50), p(plats, 99),
            ])
    print(f"\nResults written to: {path}")


# ──────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="End-to-end client: each thread is a full client "
                    "(SQS sender + WebSocket receiver).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--queue-url",   default=DEFAULT_QUEUE_URL)
    parser.add_argument("--region",      default=DEFAULT_REGION)
    parser.add_argument("--ws-url",      default=DEFAULT_WS_URL)
    parser.add_argument(
        "--threads", type=int, nargs="+", default=DEFAULT_THREADS, metavar="N",
        help="Number of concurrent clients to test (each gets its own "
             "WebSocket connection and SQS sender)",
    )
    parser.add_argument(
        "--messages", type=int, default=DEFAULT_TOTAL_MSGS, metavar="N",
        help="Messages per client per run",
    )
    parser.add_argument(
        "--rate", type=float, default=None, metavar="MSG/S",
        help="Max send rate per client in msg/s (default: unlimited)",
    )
    parser.add_argument(
        "--drain-grace", type=float, default=30.0, metavar="S",
        help="Seconds to wait after all sends complete for the pipeline to drain",
    )
    parser.add_argument("--output", default=None, metavar="FILE.csv")
    args = parser.parse_args()

    # Verify AWS credentials
    try:
        boto3.client("sts", region_name=args.region).get_caller_identity()
        print(f"AWS credentials OK  (region={args.region})", flush=True)
    except Exception as exc:
        print(f"ERROR: AWS credentials not configured: {exc}")
        sys.exit(1)

    thread_counts = sorted(set(args.threads))
    max_threads   = max(thread_counts)

    print(f"Pre-generating {max_threads} trajectories × {args.messages:,} steps ...",
          flush=True)
    trajectories = [generate_trajectory(args.messages, i) for i in range(max_threads)]
    print(f"  Done.", flush=True)

    all_results: List[RunResult] = []
    for nc in thread_counts:
        result = run_one(
            num_clients   = nc,
            trajectories  = trajectories[:nc],
            queue_url     = args.queue_url,
            region        = args.region,
            rate_limit    = args.rate,
            ws_url        = args.ws_url,
            drain_grace_s = args.drain_grace,
        )
        print_run_result(result)
        all_results.append(result)

    print_summary(all_results)
    analyze_bottlenecks(all_results)

    if args.output:
        write_csv(all_results, args.output)


if __name__ == "__main__":
    main()
