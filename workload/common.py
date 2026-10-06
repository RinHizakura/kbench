"""Shared helpers for workload/*.py.

Each workload file exports BENCHMARKS = {name: {"needs": <binary>, "fn": callable,
["repeat": n]}}; fn() returns {metric: (value, "higher"|"lower")}. kbench.py loads
every file here; running a file directly executes its benchmarks once and prints
the metrics without touching data/."""
import os, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NPROC = os.cpu_count()

def run_bench(cmd, **kw):
    """Every benchmark command goes through here: stringify args, print it,
    run it, raise on failure, return the finished process."""
    cmd = [str(c) for c in cmd]
    print("       " + " ".join(cmd), flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode:
        err = r.stderr.strip()
        raise RuntimeError(err.splitlines()[0] if err else f"{cmd[0]} exited {r.returncode}")
    return r

def parse(pattern, r, what):
    """First regex group of a finished command's output as float, or a readable error."""
    m = re.search(pattern, r.stdout + r.stderr)
    if not m:
        raise RuntimeError(f"could not parse {what} output")
    return float(m.group(1))

def main(benchmarks):
    """`python3 workload/<file>.py [name...]`: run once, print metrics, save nothing."""
    names = sys.argv[1:] or list(benchmarks)
    for name in names:
        if name not in benchmarks:
            sys.exit(f"unknown benchmark '{name}'; this file has: {', '.join(benchmarks)}")
        print(f"RUN  {name}", flush=True)
        for k, (v, better) in benchmarks[name]["fn"]().items():
            print(f"     {k} = {round(v, 3)} ({better} is better)")
