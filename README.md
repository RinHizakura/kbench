# kbench

Run a set of kernel benchmarks and compare results across kernel versions and platforms.

Latest report: <https://rinhizakura.github.io/kbench/>

## Usage

```sh
./kbench.py run
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

