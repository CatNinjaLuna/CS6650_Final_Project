#!/usr/bin/env python3
"""
VLA Service Replacement — SQS Stress Test

Simulates the VLA inference node by publishing JointAngleMessage payloads
directly to SQS, bypassing actual OpenVLA inference.  Used to stress the
worker3 → Isaac Sim → Redis → Aggregator → WebSocket pipeline.

Real VLA pipeline (what this replaces):
    Isaac Sim /camera  →  OpenVLA-7b inference  →  SQS  →  worker3  →  ...

This script:
    Pre-generated trajectories  →  SQS  →  worker3  →  ...

What is measured
----------------
* SQS publish throughput  (msgs/sec per thread, total across all threads)
* Per-thread publish rate and error count
* Optional end-to-end pipeline throughput: if --ws-url is given, a WebSocket
  listener counts SimResult messages arriving from the aggregator and computes
  an observed pipeline rate (msgs/sec delivered to the frontend)

Usage
-----
  # Smoke test — 1 thread, 1000 messages
  python vla_stress_test.py --threads 1 --messages 1000

  # Sweep thread counts with 500,000 messages each
  python vla_stress_test.py --threads 1 5 10 20 --messages 500000

  # Also monitor WebSocket to see end-to-end pipeline rate
  python vla_stress_test.py --threads 5 --messages 10000 \\
      --ws-url ws://localhost:8082/ws/results

  # Rate-limited (simulate realistic VLA inference cadence ~10 Hz)
  python vla_stress_test.py --threads 1 --rate 10

  # Multiple robot identities (one per thread)
  python vla_stress_test.py --threads 4 --device-ids arm-1 arm-2 arm-3 arm-4

  # Save results
  python vla_stress_test.py --threads 1 5 10 --output vla_results.csv

Requirements
------------
  pip install boto3 websockets
  AWS credentials must be configured (aws configure, env vars, or IAM role)
  Python >= 3.9
"""

import argparse
import asyncio
import csv
import json
import math
import statistics
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:
    print("Missing dependency: boto3\n  pip install boto3")
    sys.exit(1)

try:
    import websockets
    _WEBSOCKETS_AVAILABLE = True
except ImportError:
    _WEBSOCKETS_AVAILABLE = False


# ──────────────────────────────────────────────────────────────────
# Defaults
# ──────────────────────────────────────────────────────────────────
DEFAULT_QUEUE_URL     = "https://sqs.us-east-1.amazonaws.com/179895363911/roboparam-queue"
DEFAULT_REGION        = "us-east-1"
DEFAULT_WS_URL        = "ws://localhost:8082/ws/results"
DEFAULT_TOTAL_MSGS    = 500_000
DEFAULT_THREAD_COUNTS = [1, 5, 10, 20]
DEFAULT_DEVICE_IDS    = [f"arm-{i}" for i in range(1, 6)]

# Franka Panda joint limits (radians) from vla/VLA_EC2_SETUP.md
JOINT_LIMITS = [
    (-2.8973,  2.8973),   # joint 1
    (-1.7628,  1.7628),   # joint 2
    (-2.8973,  2.8973),   # joint 3
    (-3.0718, -0.0698),   # joint 4
    (-2.8973,  2.8973),   # joint 5
    (-0.0175,  3.7525),   # joint 6
    (-2.8973,  2.8973),   # joint 7
]

# Home/neutral pose used as trajectory midpoint
HOME_ANGLES = [0.0, -0.785, 0.0, -2.356, 0.0, 1.571, 0.785]


# ──────────────────────────────────────────────────────────────────
# Data classes
# ──────────────────────────────────────────────────────────────────
@dataclass
class ThreadStats:
    thread_id: int
    device_id: str
    messages_sent: int = 0
    errors: int = 0
    start_time: float = 0.0
    end_time: float = 0.0
    latencies_ms: List[float] = field(default_factory=list)   # SQS call duration

    @property
    def duration_s(self) -> float:
        return self.end_time - self.start_time if self.end_time > self.start_time else 0.0

    @property
    def publish_rate(self) -> float:
        return self.messages_sent / self.duration_s if self.duration_s > 0 else 0.0


@dataclass
class RunResult:
    num_threads: int
    messages_per_thread: int
    thread_stats: List[ThreadStats]
    ws_received: int = 0           # messages observed at the WebSocket (optional)
    ws_duration_s: float = 0.0

    @property
    def total_sent(self) -> int:
        return sum(s.messages_sent for s in self.thread_stats)

    @property
    def total_errors(self) -> int:
        return sum(s.errors for s in self.thread_stats)

    @property
    def wall_duration_s(self) -> float:
        starts = [s.start_time for s in self.thread_stats if s.start_time > 0]
        ends   = [s.end_time   for s in self.thread_stats if s.end_time   > 0]
        if not starts or not ends:
            return 0.0
        return max(ends) - min(starts)

    @property
    def total_publish_rate(self) -> float:
        d = self.wall_duration_s
        return self.total_sent / d if d > 0 else 0.0

    @property
    def all_sqs_latencies(self) -> List[float]:
        lats: List[float] = []
        for s in self.thread_stats:
            lats.extend(s.latencies_ms)
        return sorted(lats)

    def percentile(self, p: float) -> float:
        lats = self.all_sqs_latencies
        if not lats:
            return 0.0
        idx = min(int(len(lats) * p / 100), len(lats) - 1)
        return lats[idx]


# ──────────────────────────────────────────────────────────────────
# Trajectory generation
# ──────────────────────────────────────────────────────────────────
def generate_trajectory(n: int, device_id: str, thread_id: int) -> List[dict]:
    """
    Generate n JointAngleMessage dicts for one simulated VLA agent.

    Motion model: sinusoidal oscillation around the home pose, staying within
    Franka Panda joint limits.  Each joint oscillates at a slightly different
    frequency so the motion looks independent.  This is more realistic than
    random angles and tests the full kinematic range.

    The _send_ts field (epoch ms) is set to 0 here and overwritten at send
    time so latency can be measured accurately.
    """
    msgs = []
    # Slightly different frequency per thread so concurrent agents don't
    # produce identical trajectories
    freq_offset = 1.0 + thread_id * 0.07

    for i in range(n):
        angles = []
        for j, (lo, hi) in enumerate(JOINT_LIMITS):
            midpoint  = HOME_ANGLES[j]
            amplitude = (hi - lo) * 0.25          # swing 25% of full range
            # clamp midpoint ± amplitude to stay within limits
            amplitude = min(amplitude,
                            midpoint - lo,
                            hi - midpoint)
            freq = freq_offset * (0.8 + j * 0.05)  # slightly different per joint
            angle = midpoint + amplitude * math.sin(2 * math.pi * freq * i / max(n, 1))
            angles.append(round(angle, 4))

        msgs.append({
            "robotId":     device_id,
            "deviceId":    device_id,
            "serverId":    f"stress-server-{thread_id}",
            "clientId":    f"vla-stress-t{thread_id}",
            "jointAngles": angles,
            "timestamp":   "",     # overwritten at send time
            "_send_ts":    0,      # overwritten at send time (ms); ignored by worker3
        })
    return msgs


# ──────────────────────────────────────────────────────────────────
# SQS publisher thread
# ──────────────────────────────────────────────────────────────────
def publisher_thread(
    thread_id: int,
    device_id: str,
    messages: List[dict],
    queue_url: str,
    region: str,
    rate_limit: Optional[float],
    ready_event: threading.Event,
    stop_event: threading.Event,
    stats: ThreadStats,
) -> None:
    """
    Publishes pre-generated messages to SQS.  Each thread has its own boto3
    SQS client (clients are not thread-safe when shared).

    Stamps _send_ts and timestamp on each message immediately before sending
    so the timing is as accurate as possible.
    """
    sqs = boto3.client("sqs", region_name=region)
    delay = (1.0 / rate_limit) if rate_limit else 0.0

    ready_event.set()
    stats.start_time = time.perf_counter()

    for msg in messages:
        if stop_event.is_set():
            break

        now_ms  = time.time() * 1000
        now_iso = datetime.now(timezone.utc).isoformat()
        msg["_send_ts"]  = now_ms
        msg["timestamp"] = now_iso

        t0 = time.perf_counter()
        try:
            sqs.send_message(
                QueueUrl    = queue_url,
                MessageBody = json.dumps(msg),
            )
            sqs_latency_ms = (time.perf_counter() - t0) * 1000
            stats.latencies_ms.append(sqs_latency_ms)
            stats.messages_sent += 1
        except (BotoCoreError, ClientError) as exc:
            stats.errors += 1
            # Print first few errors; suppress the rest to avoid console flood
            if stats.errors <= 5:
                print(f"  [thread-{thread_id}] SQS error: {exc}", flush=True)

        if delay:
            time.sleep(delay)

    stats.end_time = time.perf_counter()


# ──────────────────────────────────────────────────────────────────
# Optional WebSocket monitor (measures pipeline output rate)
# ──────────────────────────────────────────────────────────────────
async def ws_monitor(
    ws_url: str,
    done_event: asyncio.Event,
    received_count: list,   # [int] — mutable so async task can write it
) -> None:
    """
    Connects to the WebSocket aggregator and counts SimResult messages
    arriving during the test.  This lets us compare:
      - How fast we published to SQS
      - How fast worker3 + Isaac Sim processed and delivered results
    """
    try:
        async with websockets.connect(ws_url, open_timeout=5) as ws:
            print(f"  WebSocket monitor connected to {ws_url}", flush=True)
            while not done_event.is_set():
                try:
                    await asyncio.wait_for(ws.recv(), timeout=0.5)
                    received_count[0] += 1
                except asyncio.TimeoutError:
                    continue
                except websockets.ConnectionClosed:
                    break
    except Exception as exc:
        print(f"  WebSocket monitor failed: {exc}", flush=True)


# ──────────────────────────────────────────────────────────────────
# Single test run
# ──────────────────────────────────────────────────────────────────
def run_one(
    num_threads: int,
    trajectories: List[List[dict]],   # one list per thread
    queue_url: str,
    region: str,
    rate_limit: Optional[float],
    ws_url: Optional[str],
) -> RunResult:
    """
    Runs num_threads publisher threads concurrently, each sending its own
    pre-generated trajectory to SQS.  Optionally starts a WebSocket monitor
    to observe pipeline throughput.
    """
    print(f"\n{'─' * 64}")
    msgs_per_thread = len(trajectories[0])
    print(f"  Threads: {num_threads}   Messages/thread: {msgs_per_thread:,}   "
          f"Total: {num_threads * msgs_per_thread:,}", flush=True)
    print(f"{'─' * 64}", flush=True)

    thread_stats  = [ThreadStats(thread_id=i, device_id=trajectories[i][0]["deviceId"])
                     for i in range(num_threads)]
    ready_events  = [threading.Event() for _ in range(num_threads)]
    stop_event    = threading.Event()

    # ── optional WebSocket monitor ────────────────────────────────
    ws_received   = [0]
    ws_done_event = None
    ws_task       = None
    ws_loop       = None
    ws_thread     = None
    ws_t_start    = 0.0

    if ws_url and _WEBSOCKETS_AVAILABLE:
        def _run_ws_loop():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            nonlocal ws_loop
            ws_loop = loop
            loop.run_forever()

        ws_thread = threading.Thread(target=_run_ws_loop, daemon=True)
        ws_thread.start()
        time.sleep(0.2)   # let the loop start

        ws_done_event = asyncio.Event()

        async def _schedule():
            return asyncio.ensure_future(
                ws_monitor(ws_url, ws_done_event, ws_received)
            )

        future = asyncio.run_coroutine_threadsafe(_schedule(), ws_loop)
        ws_task = future.result(timeout=3)
        time.sleep(1.0)   # let monitor connect before we start publishing

    # ── launch publisher threads ──────────────────────────────────
    threads = []
    for i in range(num_threads):
        t = threading.Thread(
            target=publisher_thread,
            args=(i, trajectories[i][0]["deviceId"], trajectories[i],
                  queue_url, region, rate_limit,
                  ready_events[i], stop_event, thread_stats[i]),
            daemon=True,
        )
        threads.append(t)

    print(f"  Starting {num_threads} publisher thread(s) ...", flush=True)
    ws_t_start = time.perf_counter()

    for e, t in zip(ready_events, threads):
        t.start()

    # Wait for all ready signals before printing progress
    for e in ready_events:
        e.wait(timeout=10.0)

    # Progress reporter
    def _progress():
        while any(t.is_alive() for t in threads):
            total = sum(s.messages_sent for s in thread_stats)
            errs  = sum(s.errors for s in thread_stats)
            print(f"  ... sent {total:,} / {num_threads * msgs_per_thread:,}  "
                  f"errors={errs}", flush=True)
            time.sleep(5.0)

    progress_thread = threading.Thread(target=_progress, daemon=True)
    progress_thread.start()

    for t in threads:
        t.join()

    ws_duration_s = 0.0
    if ws_done_event and ws_loop:
        # Give the pipeline a few seconds to drain before stopping the monitor
        print(f"  Waiting for pipeline to drain (10s) ...", flush=True)
        time.sleep(10.0)
        ws_duration_s = time.perf_counter() - ws_t_start
        asyncio.run_coroutine_threadsafe(
            _set_event(ws_done_event), ws_loop
        ).result(timeout=3)

    result = RunResult(
        num_threads        = num_threads,
        messages_per_thread = msgs_per_thread,
        thread_stats       = thread_stats,
        ws_received        = ws_received[0],
        ws_duration_s      = ws_duration_s,
    )
    return result


async def _set_event(event: asyncio.Event) -> None:
    event.set()


# ──────────────────────────────────────────────────────────────────
# Output
# ──────────────────────────────────────────────────────────────────
def print_run_result(r: RunResult) -> None:
    lats = r.all_sqs_latencies
    has_lat = bool(lats)

    print(f"\n  Results:")
    print(f"    Threads:                 {r.num_threads:>12}")
    print(f"    Messages sent:           {r.total_sent:>12,}")
    print(f"    SQS errors:              {r.total_errors:>12,}")

    if r.total_sent > 0:
        err_pct = r.total_errors / (r.total_sent + r.total_errors) * 100
        print(f"    Error rate:              {err_pct:>11.2f}%")

    print(f"    Wall duration:           {r.wall_duration_s:>11.2f}s")
    print(f"    Total publish rate:      {r.total_publish_rate:>11,.0f} msg/s")

    per_thread_rates = [s.publish_rate for s in r.thread_stats if s.messages_sent > 0]
    if per_thread_rates:
        print(f"    Per-thread rate:         "
              f"{min(per_thread_rates):,.0f}–{max(per_thread_rates):,.0f} msg/s  "
              f"(mean {statistics.mean(per_thread_rates):,.0f})")

    if has_lat:
        print(f"\n  SQS send() call latency:")
        print(f"    Samples:   {len(lats):>12,}")
        print(f"    Min:       {min(lats):>11.2f} ms")
        print(f"    Mean:      {statistics.mean(lats):>11.2f} ms")
        print(f"    p50:       {r.percentile(50):>11.2f} ms")
        print(f"    p95:       {r.percentile(95):>11.2f} ms")
        print(f"    p99:       {r.percentile(99):>11.2f} ms")
        print(f"    Max:       {max(lats):>11.2f} ms")

    if r.ws_received > 0:
        pipeline_rate = r.ws_received / r.ws_duration_s if r.ws_duration_s > 0 else 0
        backlog = r.total_sent - r.ws_received
        print(f"\n  Pipeline throughput  (SQS → worker3 → Isaac Sim → WebSocket):")
        print(f"    WS messages received:    {r.ws_received:>12,}")
        print(f"    Pipeline rate:           {pipeline_rate:>11,.1f} msg/s")
        print(f"    Unprocessed backlog:     {backlog:>12,}  "
              f"({'still processing' if backlog > 0 else 'fully drained'})")


def print_summary(results: List[RunResult]) -> None:
    print(f"\n{'═' * 82}")
    print("BENCHMARK SUMMARY")
    print(f"{'═' * 82}")
    hdr = (f"{'Threads':>8}  {'Sent':>10}  {'Errors':>8}  "
           f"{'Total/s':>9}  {'p50ms':>7}  {'p99ms':>7}  "
           f"{'WS Rcvd':>10}  {'Pipeline/s':>11}")
    print(hdr)
    print("─" * 82)
    for r in results:
        lats = r.all_sqs_latencies
        p50  = r.percentile(50) if lats else 0.0
        p99  = r.percentile(99) if lats else 0.0
        pip_rate = r.ws_received / r.ws_duration_s if r.ws_received > 0 and r.ws_duration_s > 0 else 0.0
        print(f"{r.num_threads:>8}  {r.total_sent:>10,}  {r.total_errors:>8,}  "
              f"{r.total_publish_rate:>9,.0f}  {p50:>7.1f}  {p99:>7.1f}  "
              f"{r.ws_received:>10,}  {pip_rate:>11,.1f}")


def analyze_bottlenecks(results: List[RunResult]) -> None:
    valid = [r for r in results if r.total_sent > 0]
    if not valid:
        return

    print(f"\n{'═' * 82}")
    print("BOTTLENECK ANALYSIS")
    print(f"{'═' * 82}")

    findings: List[str] = []
    warnings: List[str] = []

    baseline = valid[0]

    # ── 1. SQS publish latency degradation ───────────────────────
    if len(valid) >= 2:
        lat_series = [(r.num_threads, r.percentile(99))
                      for r in valid if r.all_sqs_latencies]
        if len(lat_series) >= 2:
            c0, p0 = lat_series[0]
            degraded = False
            knee = None
            for c, p in lat_series[1:]:
                if p > p0 * 2.0:
                    degraded = True
                    if knee is None:
                        knee = c
            if degraded:
                findings.append(
                    f"[SQS LATENCY]  p99 SQS send latency more than doubled "
                    f"from {lat_series[0][1]:.0f}ms (1 thread) — "
                    f"visible from {knee} threads onward.  "
                    f"Likely cause: SQS throttling or network saturation.\n"
                    f"    Fix: use SQS batch sending (send_message_batch, up to 10 "
                    f"messages per call) to reduce per-message overhead."
                )
            else:
                warnings.append(
                    "[OK] SQS p99 latency stable across thread counts — "
                    "no SQS-side throttling detected."
                )

    # ── 2. Publish rate scaling ───────────────────────────────────
    if len(valid) >= 2:
        rates = [(r.num_threads, r.total_publish_rate) for r in valid]
        t0_rate = rates[0][1]
        # Check if doubling threads yields < 80% of expected doubling
        scaling_issues = []
        for i in range(1, len(rates)):
            t_prev, r_prev = rates[i - 1]
            t_curr, r_curr = rates[i]
            if t_prev == 0:
                continue
            scale_factor   = t_curr / t_prev
            expected_rate  = r_prev * scale_factor
            actual_gain    = r_curr / expected_rate if expected_rate > 0 else 1.0
            if actual_gain < 0.7:   # getting less than 70% of expected gain
                scaling_issues.append((t_curr, actual_gain * 100))

        if scaling_issues:
            worst_t, worst_pct = scaling_issues[0]
            findings.append(
                f"[PUBLISH SCALING]  Adding threads yields diminishing returns "
                f"from {worst_t} threads ({worst_pct:.0f}% of expected linear gain).  "
                f"Bottleneck is likely:\n"
                f"    • SQS per-queue throughput limit (~3,000 msg/s for standard queues)\n"
                f"    • boto3 connection pool exhaustion (default max_pool_connections=10)\n"
                f"    Fix: use a FIFO queue or request a throughput increase; "
                f"configure botocore Config(max_pool_connections=num_threads)."
            )
        else:
            warnings.append(
                "[OK] Publish rate scales roughly linearly with thread count — "
                "no SQS throughput ceiling hit."
            )

    # ── 3. Error rate ─────────────────────────────────────────────
    for r in valid:
        total_attempts = r.total_sent + r.total_errors
        if total_attempts > 0:
            err_pct = r.total_errors / total_attempts * 100
            if err_pct > 1.0:
                findings.append(
                    f"[SQS ERRORS]  {r.total_errors:,} send failures at "
                    f"{r.num_threads} threads ({err_pct:.1f}% error rate).  "
                    f"Check AWS credentials, queue URL, and IAM permissions."
                )

    # ── 4. Pipeline throughput vs publish rate ────────────────────
    for r in valid:
        if r.ws_received > 0 and r.total_sent > 0:
            pipeline_rate  = r.ws_received / r.ws_duration_s if r.ws_duration_s > 0 else 0
            publish_rate   = r.total_publish_rate
            if publish_rate > 0:
                ratio = pipeline_rate / publish_rate
                if ratio < 0.1:
                    findings.append(
                        f"[PIPELINE BOTTLENECK]  At {r.num_threads} threads, "
                        f"pipeline throughput ({pipeline_rate:.1f} msg/s) is only "
                        f"{ratio*100:.0f}% of publish rate ({publish_rate:.0f} msg/s).  "
                        f"The bottleneck is downstream of SQS:\n"
                        f"    • worker3 polls in batches of 5 with 500ms fixed delay — "
                        f"max ~10 msg/s per instance\n"
                        f"    • Isaac Sim processes one joint update at a time (synchronous HTTP)\n"
                        f"    Fix: run multiple worker3 instances, or switch Isaac Sim "
                        f"calls to async/batch processing."
                    )
                elif ratio < 0.5:
                    warnings.append(
                        f"[PIPELINE LAG]  Pipeline rate ({pipeline_rate:.1f} msg/s) is "
                        f"{ratio*100:.0f}% of publish rate at {r.num_threads} threads — "
                        f"a backlog is building in SQS.  "
                        f"worker3 + Isaac Sim cannot keep up at this publish rate."
                    )

    # ── 5. SQS backlog ────────────────────────────────────────────
    if any(r.ws_received > 0 for r in valid):
        total_backlog = sum(r.total_sent - r.ws_received
                            for r in valid if r.ws_received > 0)
        if total_backlog > 1000:
            warnings.append(
                f"[SQS BACKLOG]  ~{total_backlog:,} messages remain unprocessed "
                f"in the SQS queue after the test.  worker3 will continue consuming "
                f"them after the test ends — check the queue depth in the AWS console."
            )

    # ── print ─────────────────────────────────────────────────────
    if findings:
        print(f"\n  {'─'*38}  PROBLEMS  {'─'*31}")
        for i, f in enumerate(findings, 1):
            lines = f.split("\n")
            print(f"\n  {i}. {lines[0]}")
            for line in lines[1:]:
                print(f"     {line}")
    else:
        print("\n  No significant bottlenecks detected at the tested thread counts.")

    if warnings:
        print(f"\n  {'─'*40}  INFO  {'─'*33}")
        for w in warnings:
            print(f"  • {w}")

    print()


def write_csv(results: List[RunResult], path: str) -> None:
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "threads", "messages_sent", "total_errors",
            "wall_duration_s", "total_publish_rate_msg_s",
            "sqs_lat_min_ms", "sqs_lat_mean_ms",
            "sqs_lat_p50_ms", "sqs_lat_p95_ms", "sqs_lat_p99_ms",
            "sqs_lat_max_ms",
            "ws_received", "pipeline_rate_msg_s",
        ])
        for r in results:
            lats = r.all_sqs_latencies
            pip  = r.ws_received / r.ws_duration_s if r.ws_received > 0 and r.ws_duration_s > 0 else ""
            writer.writerow([
                r.num_threads,
                r.total_sent,
                r.total_errors,
                f"{r.wall_duration_s:.3f}",
                f"{r.total_publish_rate:.1f}",
                f"{min(lats):.2f}"              if lats else "",
                f"{statistics.mean(lats):.2f}"  if lats else "",
                f"{r.percentile(50):.2f}"       if lats else "",
                f"{r.percentile(95):.2f}"       if lats else "",
                f"{r.percentile(99):.2f}"       if lats else "",
                f"{max(lats):.2f}"              if lats else "",
                r.ws_received,
                f"{pip:.1f}" if pip != "" else "",
            ])
    print(f"\nResults written to: {path}")


# ──────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="VLA replacement stress test — publishes JointAngleMessage to SQS.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--queue-url",  default=DEFAULT_QUEUE_URL,  help="SQS queue URL")
    parser.add_argument("--region",     default=DEFAULT_REGION,     help="AWS region")
    parser.add_argument(
        "--threads", type=int, nargs="+", default=DEFAULT_THREAD_COUNTS, metavar="N",
        help="Number of concurrent publisher threads to test (space-separated)",
    )
    parser.add_argument(
        "--messages", type=int, default=DEFAULT_TOTAL_MSGS, metavar="N",
        help="Messages per thread per run",
    )
    parser.add_argument(
        "--device-ids", nargs="+", default=DEFAULT_DEVICE_IDS, metavar="ID",
        help="Robot device IDs to cycle across threads",
    )
    parser.add_argument(
        "--rate", type=float, default=None, metavar="MSG/S",
        help="Max publish rate per thread in msg/s (default: unlimited)",
    )
    parser.add_argument(
        "--ws-url", default=None, metavar="URL",
        help=f"WebSocket URL to monitor pipeline output (default: off).  "
             f"Example: {DEFAULT_WS_URL}",
    )
    parser.add_argument(
        "--output", default=None, metavar="FILE.csv",
        help="Write results to CSV",
    )
    args = parser.parse_args()

    if args.ws_url and not _WEBSOCKETS_AVAILABLE:
        print("WARNING: --ws-url given but websockets library not installed.  "
              "WebSocket monitoring disabled.\n  pip install websockets")
        args.ws_url = None

    # Verify AWS credentials early
    try:
        boto3.client("sts", region_name=args.region).get_caller_identity()
        print(f"AWS credentials OK  (region={args.region})", flush=True)
    except Exception as exc:
        print(f"ERROR: AWS credentials not configured: {exc}")
        print("  Run: aws configure   or set AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY")
        sys.exit(1)

    thread_counts = sorted(set(args.threads))
    max_threads   = max(thread_counts)

    # Pre-generate one trajectory per thread slot (reused across runs)
    print(f"Pre-generating {max_threads} trajectories × {args.messages:,} messages ...",
          flush=True)
    t0 = time.perf_counter()
    device_ids  = args.device_ids
    trajectories = [
        generate_trajectory(args.messages, device_ids[i % len(device_ids)], i)
        for i in range(max_threads)
    ]
    elapsed = time.perf_counter() - t0
    print(f"  Done in {elapsed:.2f}s", flush=True)

    all_results: List[RunResult] = []
    for nc in thread_counts:
        result = run_one(
            num_threads  = nc,
            trajectories = trajectories[:nc],
            queue_url    = args.queue_url,
            region       = args.region,
            rate_limit   = args.rate,
            ws_url       = args.ws_url,
        )
        print_run_result(result)
        all_results.append(result)

    print_summary(all_results)
    analyze_bottlenecks(all_results)

    if args.output:
        write_csv(all_results, args.output)


if __name__ == "__main__":
    main()
