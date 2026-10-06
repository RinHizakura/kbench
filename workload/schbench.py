"""schbench: heavy (2x oversubscribed) rps + request latency; light (N/2 workers) wake latency."""
import re
from common import NPROC, run_bench, parse, main

def _bench_schbench(mthreads, workers):
    """Scheduler wakeup + request latency p50/p99/p99.9 + avg rps."""
    # long runtime + warmup: p99/p99.9 need many requests per run to converge
    r = run_bench(["schbench", "-m", mthreads, "-t", workers, "-r", "120", "-w", "5"])
    text = r.stdout + r.stderr  # schbench prints to stderr
    out = {}
    wake, _, req = text.partition("Request Latencies")  # old format: no marker -> req empty
    req = req.partition("RPS percentiles")[0]
    for prefix, block in (("wake_", wake), ("req_", req)):
        for pct, val in re.findall(r"\*?\s*(\d+\.\d)th:\s+(\d+)", block):
            if pct in ("50.0", "99.0", "99.9") and f"{prefix}p{pct}_us" not in out:
                out[f"{prefix}p{pct}_us"] = (int(val), "lower")
    out["avg_rps"] = (parse(r"average rps:\s+([\d.]+)", r, "schbench rps"), "higher")
    return out

def bench_schbench_heavy():
    """2x oversubscribed (CPU saturated): rps + req latency are the meaningful
    metrics, wake latency just reads back preemption granularity."""
    return _bench_schbench(2, NPROC)

def bench_schbench_light():
    """Underloaded (N/2 workers): wake latency measures scheduler responsiveness."""
    return _bench_schbench(1, max(1, NPROC // 2))

# 9 reps: governor-sensitive, median over 9 keeps the estimate stable.
BENCHMARKS = {
    "schbench-heavy": {"needs": "schbench", "fn": bench_schbench_heavy, "repeat": 9},
    "schbench-light": {"needs": "schbench", "fn": bench_schbench_light},
}

if __name__ == "__main__":
    main(BENCHMARKS)
