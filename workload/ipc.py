"""Scheduler+IPC throughput, hackbench-style (perf bench sched messaging)."""
from common import run_bench, parse, main

def bench_ipc():
    r = run_bench(["perf", "bench", "sched", "messaging", "-g", "10", "-l", "1000"])
    return {"total_s": (parse(r"Total time:\s+([\d.]+)", r, "perf messaging"), "lower")}

BENCHMARKS = {"ipc": {"needs": "perf", "fn": bench_ipc}}

if __name__ == "__main__":
    main(BENCHMARKS)
