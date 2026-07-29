# kbench

Performance regression testing across kernel updates. Runs benchmarks, saves JSON results, and
generates a static `index.html` to view or compare them — anything >5% worse is flagged red.

## Usage

```sh
# 1. On the old kernel: create a baseline
./kbench.py run

# 2. Reboot into the new kernel, run again
./kbench.py run
```

Every run creates its own folder `runs/<kernel>_nN/` (N = highest existing number + 1,
so higher = newer) containing:

- `result.json` — raw metrics + sysinfo
- `index.html` — the run by itself
- `vs_baseline.html` — compared against the oldest run
- `vs_prev.html` — compared against the previous run

Comparison pages are skipped on the very first run. To delete a run, delete its folder.
Pages show sysinfo (kernel, cmdline, governor) as a table — in comparisons, fields that
differ between the two runs are highlighted. A benchmark dropdown filters the table to a
single testcase.

`./kbench.py run <bench...>` runs a subset (e.g. `./kbench.py run net syscall`), and
`--output DIR` stores results under `DIR/` instead of `runs/` (a separate result set with
its own history and baseline).
Benchmarks whose tool is missing are skipped and listed in the report; `./setup.sh`
installs all dependencies. `rtla` needs root — use `sudo ./kbench.py run` to include it.

## Benchmarks

| name       | needs       | measures                                                                 |
|------------|-------------|--------------------------------------------------------------------------|
| fio        | fio         | block I/O: 4k rand r/w IOPS + p99 lat, 1M seq throughput, 4k fsync write |
| schbench   | schbench    | scheduler wakeup latency p50/p99/p99.9, avg rps                          |
| rtla       | rtla (root) | timer IRQ/thread wakeup latency (timerlat)                               |
| memory     | sysbench    | memory bandwidth, read/write MiB/s                                       |
| net        | iperf3      | loopback TCP Gbps (plain + zero-copy), 64B UDP pps (1 + N streams)       |
| syscall    | perf        | syscall entry/exit overhead                                              |
| perf-sched | perf        | context-switch cost (sched pipe)                                         |
| ipc        | perf        | scheduler+IPC throughput (hackbench-style)                               |
| pagefault  | stress-ng   | page-fault rate                                                          |
| fork       | stress-ng   | fork/exec rate                                                           |

