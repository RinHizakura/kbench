# kbench

Run a set of kernel benchmarks and compare results across kernel versions and platforms.

Latest report: <https://rinhizakura.github.io/kbench/>

## Usage

```sh
./kbench.py run                  # all benchmarks -> data/runs/results.json
./kbench.py run --output rpi4    # per-platform data dir -> data/rpi4/ (results.json, hw.json, configs/)
./kbench.py list --output rpi4   # list saved runs
./kbench.py rm <run> --output rpi4
python3 -m http.server            # view report locally at http://localhost:8000
```

Each benchmark lives in `workload/<name>.py`. Run one directly to execute it once and
print its metrics without saving anything (e.g. `sudo python3 workload/perf-pipe.py`,
`python3 workload/schbench.py schbench-light`).

## Benchmarks

| name       | needs       | measures                                                                 |
|------------|-------------|--------------------------------------------------------------------------|
| fio        | fio         | block I/O: 4k rand r/w IOPS + p99 lat, 1M seq throughput, 4k fsync write |
| schbench   | schbench    | heavy (2x oversubscribed): rps + req latency; light (N/2 workers): wake latency |
| memory-256k | sysbench   | cache-regime memory bandwidth, read/write MiB/s (256K blocks)            |
| memory-64m | sysbench    | DRAM-regime memory bandwidth, read/write MiB/s (64M blocks)              |
| net        | iperf3      | loopback TCP Gbps (plain + zero-copy), 64B UDP pps (1 + N streams)       |
| syscall    | perf        | syscall entry/exit overhead                                              |
| ipc        | perf        | scheduler+IPC throughput (hackbench-style)                               |
| perf-pipe  | perf       | pinned pipe ping-pong wakeup cost from the root cgroup and 16 cpu-cgroup levels deep (creates cgroups, so run as root) |
| pagefault  | stress-ng   | page-fault rate                                                          |
| fork       | stress-ng   | fork/exec rate                                                           |

