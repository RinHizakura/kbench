"""Wakeup-path cost vs cgroup nesting depth: perf bench sched pipe pinned to one CPU,
run from the root cgroup and from leaves 1 and 8 cpu-cgroup levels deep. Needs root."""
import os, time
from pathlib import Path
from common import NPROC, run_bench, parse, main

CG_ROOT = Path("/sys/fs/cgroup")
PIPE_DEPTHS = (0, 1, 8)  # root, systemd-service-like, container-like nesting

def _in_cgroup(leaf, cpu=None):
    """preexec_fn: move the child into cgroup LEAF (and pin it to CPU) before exec.
    Everything perf forks inherits both."""
    def pre():
        if cpu is not None:
            os.sched_setaffinity(0, {cpu})
        (leaf / "cgroup.procs").write_text(str(os.getpid()))
    return pre

def _nested_cgroup(depth):
    """/sys/fs/cgroup/kbench-d<depth>/l2/.../l<depth> with the cpu controller
    enabled at every level (one cfs_rq per level). Returns the leaf (root for 0)."""
    path = CG_ROOT
    for i in range(depth):
        (path / "cgroup.subtree_control").write_text("+cpu")  # idempotent
        path = path / (f"kbench-d{depth}" if i == 0 else f"l{i + 1}")
        path.mkdir(exist_ok=True)
    return path

def _rm_cgroup(leaf, depth):
    for _ in range(depth):
        for _ in range(50):  # exiting children linger in cgroup.procs for a moment
            try:
                leaf.rmdir()
                break
            except OSError:
                time.sleep(0.02)
        leaf = leaf.parent

def bench_perf_pipe():
    """perf bench sched pipe pinned to one CPU, so every message is one
    dequeue+enqueue+pick, run from the root cgroup and from leaves 1 and 8
    cpu-cgroup levels deep: d0 is the bare wakeup path, d1-d0 the cost of
    group scheduling, d8-d1 how it scales with nesting (CONFIG_FAIR_GROUP_SCHED).
    Needs root for the cgroup writes."""
    if os.geteuid():
        raise RuntimeError("needs root (creates cgroups under /sys/fs/cgroup)")
    if "cpu" not in (CG_ROOT / "cgroup.controllers").read_text().split():
        raise RuntimeError("cgroup v2 cpu controller not available")
    out = {}
    for depth in PIPE_DEPTHS:
        leaf = _nested_cgroup(depth)
        try:
            r = run_bench(["perf", "bench", "sched", "pipe", "-l", 1000000],
                          preexec_fn=_in_cgroup(leaf, cpu=NPROC - 1))
            out[f"d{depth}.usecs_op"] = (parse(r"([\d.]+) usecs/op", r, "perf pipe"), "lower")
        finally:
            _rm_cgroup(leaf, depth)
    return out

BENCHMARKS = {"perf-pipe": {"needs": "perf", "fn": bench_perf_pipe}}

if __name__ == "__main__":
    main(BENCHMARKS)
