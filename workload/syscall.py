"""Syscall entry/exit overhead (perf bench syscall basic)."""
from common import run_bench, parse, main

def bench_syscall():
    r = run_bench(["perf", "bench", "syscall", "basic"])
    return {"usecs_op": (parse(r"([\d.]+) usecs/op", r, "perf syscall"), "lower")}

BENCHMARKS = {"syscall": {"needs": "perf", "fn": bench_syscall}}

if __name__ == "__main__":
    main(BENCHMARKS)
