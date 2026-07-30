# kbench

Run a set of kernel benchmarks and compare results across kernel versions and platforms.

Latest report: <https://rinhizakura.github.io/kbench/>

## Usage

```sh
./kbench.py run                  # all benchmarks -> data/runs.json
./kbench.py run --output rpi4    # per-platform result set -> data/rpi4.json
./kbench.py list --output rpi4   # list saved runs
./kbench.py rm <run> --output rpi4
python3 -m http.server            # view report locally at http://localhost:8000
```

## Benchmarks

| name       | needs       | measures                                                                 |
|------------|-------------|--------------------------------------------------------------------------|
| fio        | fio         | block I/O: 4k rand r/w IOPS + p99 lat, 1M seq throughput, 4k fsync write |
| schbench   | schbench    | scheduler wakeup latency p50/p99/p99.9, avg rps                          |
| memory     | sysbench    | memory bandwidth, read/write MiB/s                                       |
| net        | iperf3      | loopback TCP Gbps (plain + zero-copy), 64B UDP pps (1 + N streams)       |
| syscall    | perf        | syscall entry/exit overhead                                              |
| perf-sched | perf        | context-switch cost (sched pipe)                                         |
| ipc        | perf        | scheduler+IPC throughput (hackbench-style)                               |
| pagefault  | stress-ng   | page-fault rate                                                          |
| fork       | stress-ng   | fork/exec rate                                                           |

