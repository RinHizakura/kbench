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
differ between the two runs are highlighted.

## Benchmarks

| name     | measures                                                              |
|----------|-----------------------------------------------------------------------|
| fio      | block I/O: 4k randread/randwrite IOPS, 1M seqread/seqwrite throughput |
| schbench | scheduler wakeup latency p50/p99/p99.9                                |

