"""stress-ng rates: page faults (fault) and fork/exec (fork), N workers x 15s."""
from common import NPROC, run_bench, parse, main

def _stressng(stressor):
    """bogo ops/s (real time) for one stress-ng stressor, N workers x 15s."""
    r = run_bench(["stress-ng", f"--{stressor}", NPROC, "-t", "15", "--metrics-brief"])
    v = parse(rf"{stressor}\s+\d+\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+([\d.]+)",  # 5th col = bogo ops/s (real)
              r, f"stress-ng {stressor}")
    return {"bogo_ops_s": (v, "higher")}

BENCHMARKS = {
    "pagefault": {"needs": "stress-ng", "fn": lambda: _stressng("fault")},
    "fork":      {"needs": "stress-ng", "fn": lambda: _stressng("fork")},
}

if __name__ == "__main__":
    main(BENCHMARKS)
