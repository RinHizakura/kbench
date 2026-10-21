"""Timer wakeup latency via rtla timerlat: a 1ms periodic timer on every CPU, latency
measured at the IRQ handler, the woken kernel thread, and the return to a user
thread. max is over all CPUs; avg is the mean of the per-CPU averages. Needs root
(tracefs) and CONFIG_TIMERLAT_TRACER."""
import os, re
from common import run_bench, main

DURATION = 30  # s, 1ms period -> 30k samples per CPU per rep

def bench_timerlat():
    if os.geteuid():
        raise RuntimeError("needs root (tracefs)")
    r = run_bench(["rtla", "timerlat", "top", "-u", "-q", "-d", f"{DURATION}s"])
    # per-CPU rows: "<cpu> #<n> | cur min avg max | cur min avg max | cur min avg max"
    # (irq | thread | user); cur may be "-", so take the last three numbers of each group.
    groups = {"irq": [], "thread": [], "user": []}
    for line in r.stdout.splitlines():
        if not re.match(r"\s*\d+\s+#\d+", line):
            continue
        cols = line.split("|")[1:]
        for name, col in zip(groups, cols):
            mn, avg, mx = map(float, col.split()[-3:])
            groups[name].append((avg, mx))
    if not groups["thread"]:
        raise RuntimeError("could not parse rtla timerlat output")
    out = {}
    for name, rows in groups.items():
        if rows:
            out[f"{name}.max_us"] = (max(mx for _, mx in rows), "lower")
            out[f"{name}.avg_us"] = (sum(avg for avg, _ in rows) / len(rows), "lower")
    return out

BENCHMARKS = {"timerlat": {"needs": "rtla", "fn": bench_timerlat}}

if __name__ == "__main__":
    main(BENCHMARKS)
