"""schbench: heavy (2x oversubscribed) rps + req p99; light (N/2 workers) wake p99."""
import re
from common import NPROC, run_bench, parse, main

def _bench_schbench(mthreads, workers, keep):
    """Run schbench and return the metrics named in `keep`: wake_p<pct>_us,
    req_p<pct>_us (pct in 50.0/99.0/99.9) and avg_rps."""
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
    return {k: out[k] for k in keep}

def bench_schbench_heavy():
    """2x oversubscribed (CPU saturated): throughput + request tail. wake latency
    just reads back preemption granularity, req_p50 is 1/rps, req_p99.9 is noise."""
    return _bench_schbench(2, NPROC, ["avg_rps", "req_p99.0_us"])

def bench_schbench_light():
    """Underloaded (N/2 workers): wake latency measures scheduler responsiveness.
    req_* and rps are fixed by the per-request work here; p50 is 1us-quantized and
    p99.9 does not settle in 5 reps, so only wake_p99 is kept."""
    return _bench_schbench(1, max(1, NPROC // 2), ["wake_p99.0_us"])

# 9 reps: governor-sensitive, median over 9 keeps the estimate stable.
BENCHMARKS = {
    "schbench-heavy": {"needs": "schbench", "fn": bench_schbench_heavy, "repeat": 9},
    "schbench-light": {"needs": "schbench", "fn": bench_schbench_light},
}

if __name__ == "__main__":
    main(BENCHMARKS)
