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

## Manual runs

The same commands kbench runs, for reproducing one benchmark by hand:

```sh
# fio — one line per job; kbench adds --output-format=json for parsing
fio --name randread-4k  --filename=testfile --size=1g --runtime=30 --time_based \
    --ioengine=libaio --direct=1 --group_reporting --rw=randread --bs=4k --iodepth=32
#   randwrite-4k: --rw=randwrite --bs=4k --iodepth=32
#   seqread-1m:   --rw=read     --bs=1m --iodepth=8
#   seqwrite-1m:  --rw=write    --bs=1m --iodepth=8
#   syncwrite-4k: --rw=randwrite --bs=4k --iodepth=1 --fsync=1

# schbench
schbench -m 2 -t $(nproc) -r 30

# memory (run once per --memory-oper=read|write)
sysbench memory --memory-block-size=1M --memory-total-size=20G --memory-oper=read run

# net — server in one shell, client in another; variants: -Z (tcp zero-copy),
# -u -b 0 -l 64 (udp 64B), -u -b 0 -l 64 -P $(nproc) (udp multi-stream)
iperf3 -s -1 -p 5210
iperf3 -c 127.0.0.1 -p 5210 -t 10

# syscall / perf-sched / ipc
perf bench syscall basic
perf bench sched pipe
perf bench sched messaging -g 10 -l 1000

# pagefault / fork
stress-ng --fault $(nproc) -t 15 --metrics-brief
stress-ng --fork  $(nproc) -t 15 --metrics-brief
```

