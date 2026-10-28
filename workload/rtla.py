"""rtla timerlat: a 1ms periodic timer on every CPU, latency at the IRQ handler, the woken
kernel thread and the return to a user thread; p99/p99.9 over all samples, max over
CPUs, mean of the per-CPU averages. Needs root (tracefs) and CONFIG_TIMERLAT_TRACER."""
import os, re
from common import run_bench, main

DURATION = 30  # s per rep; timerlat's 1ms period -> 30k samples per CPU
ENTRIES = 4096  # timerlat hist buckets of 1us; samples past this land in "over:"

def _root():
    if os.geteuid():
        raise RuntimeError("needs root (tracefs)")

def _pct(hist, p):
    """p-quantile (0-1) of a {latency_us: count} histogram."""
    total, acc = sum(hist.values()), 0
    for us in sorted(hist):
        acc += hist[us]
        if acc >= p * total:
            return us

def bench_timerlat():
    _root()
    r = run_bench(["rtla", "timerlat", "hist", "-u", "-d", f"{DURATION}s", "-E", ENTRIES])
    # "Index IRQ-000 Thr-000 Usr-000 IRQ-001 ..." header, one row per 1us bucket (zero
    # rows omitted), then over:/count:/min:/avg:/max: rows with the same columns.
    lines = r.stdout.splitlines()
    cols = next((l.split()[1:] for l in lines if l.startswith("Index")), None)
    if not cols:
        raise RuntimeError("could not parse rtla timerlat output")
    kinds = [{"IRQ": "irq", "Thr": "thread", "Usr": "user"}[c[:3]] for c in cols]
    hist = {k: {} for k in kinds}
    summ = {}
    for line in lines:
        f = line.split()
        if len(f) != len(cols) + 1:
            continue
        if f[0].isdigit():
            for kind, n in zip(kinds, f[1:]):
                hist[kind][int(f[0])] = hist[kind].get(int(f[0]), 0) + int(n)
        elif f[0] in ("over:", "avg:", "max:"):
            summ[f[0][:-1]] = [float(x) for x in f[1:]]
    out = {}
    for kind in dict.fromkeys(kinds):
        idx = [i for i, k in enumerate(kinds) if k == kind]
        h = hist[kind]
        if over := int(sum(summ.get("over", [0] * len(cols))[i] for i in idx)):
            h[ENTRIES] = h.get(ENTRIES, 0) + over  # past the last bucket: clamp to ENTRIES
        out[f"{kind}.p99_us"] = (_pct(h, .99), "lower")
        out[f"{kind}.p99.9_us"] = (_pct(h, .999), "lower")
        out[f"{kind}.avg_us"] = (sum(summ["avg"][i] for i in idx) / len(idx), "lower")
        out[f"{kind}.max_us"] = (max(summ["max"][i] for i in idx), "lower")
    return out

BENCHMARKS = {"timerlat": {"needs": "rtla", "fn": bench_timerlat}}

if __name__ == "__main__":
    main(BENCHMARKS)
