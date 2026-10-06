"""Memory bandwidth via sysbench: 256K blocks (cache regime) and 64M blocks (DRAM regime)."""
from common import run_bench, parse, main

def _bench_memory(blk):
    """Memory bandwidth via sysbench. 256K block = cache regime, 64M = DRAM regime;
    1M blocks sit exactly on the RPi4 L2 size, where page-coloring luck swings
    results by ±15% per run — these two sizes are stable to <1%."""
    out = {}
    for op in ("read", "write"):
        r = run_bench(["sysbench", "memory", f"--memory-block-size={blk}",
                       "--memory-total-size=20G", f"--memory-oper={op}", "run"])
        out[f"{op}.bw_mibps"] = (parse(r"\(([\d.]+) MiB/sec\)", r, f"sysbench {op}"), "higher")
    return out

BENCHMARKS = {
    "memory-256k": {"needs": "sysbench", "fn": lambda: _bench_memory("256K")},
    "memory-64m":  {"needs": "sysbench", "fn": lambda: _bench_memory("64M")},
}

if __name__ == "__main__":
    main(BENCHMARKS)
