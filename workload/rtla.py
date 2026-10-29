"""rtla tracers (need root for tracefs):
timerlat — a 1ms periodic timer on every CPU, latency until a user thread runs (irq +
kernel thread + return to user); p99.9 over all samples and max over CPUs
(CONFIG_TIMERLAT_TRACER).
osnoise — a busy loop on every CPU, counting the time stolen by irqs, softirqs, NMIs
and other threads (CONFIG_OSNOISE_TRACER)."""
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
    # Only the user-thread latency is kept: it is what an application sees and already
    # contains the irq and kernel-thread legs. irq.* was identical across kernels (board
    # floor), avg barely moves, p99 is bimodal on non-RT; run rtla by hand to see the layers.
    idx = [i for i, k in enumerate(kinds) if k == "user"]
    h = hist["user"]
    if over := int(sum(summ.get("over", [0] * len(cols))[i] for i in idx)):
        h[ENTRIES] = h.get(ENTRIES, 0) + over  # past the last bucket: clamp to ENTRIES
    return {"p99.9_us": (_pct(h, .999), "lower"),
            "max_us": (max(summ["max"][i] for i in idx), "lower")}

def bench_osnoise():
    """noise_us: time stolen from the busy loops, summed over CPUs for the whole run.
    max_noise_us: worst single 1s period; max_single_us: longest single interruption."""
    _root()
    r = run_bench(["rtla", "osnoise", "top", "-q", "-d", f"{DURATION}s"])
    # per-CPU rows: "<cpu> #<periods> <runtime> <noise> <%avail> <max noise> <max single> HW NMI IRQ Softirq Thread"
    rows = [l.split() for l in r.stdout.splitlines() if re.match(r"\s*\d+\s+#\d+", l)]
    if not rows:
        raise RuntimeError("could not parse rtla osnoise output")
    return {"noise_us": (sum(float(f[3]) for f in rows), "lower"),
            "max_noise_us": (max(float(f[5]) for f in rows), "lower"),
            "max_single_us": (max(float(f[6]) for f in rows), "lower")}

BENCHMARKS = {"timerlat": {"needs": "rtla", "fn": bench_timerlat},
              "osnoise": {"needs": "rtla", "fn": bench_osnoise}}

if __name__ == "__main__":
    main(BENCHMARKS)
