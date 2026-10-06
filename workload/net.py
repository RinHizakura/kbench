"""Loopback networking via iperf3: TCP Gbps (plain + zero-copy), 64B UDP pps (1 + N streams)."""
import json, subprocess, time
from common import NPROC, run_bench, main

def bench_net():
    """Loopback TCP Gbps (plain + zero-copy), 64B UDP pps (1 + N streams)."""
    bw = lambda e: ("bw_gbps", e["sum_received"]["bits_per_second"] / 1e9)
    pps = lambda e: ("pps", e["sum"]["packets"] / e["sum"]["seconds"])
    udp = ["-u", "-b", "0", "-l", "64"]
    out = {}
    for name, extra, metric in [
        ("tcp",           [],                  bw),
        ("tcp-zc",        ["-Z"],              bw),   # zero-copy (sendfile) send path
        ("udp-64b",       udp,                 pps),
        ("udp-64b-multi", udp + ["-P", NPROC], pps),
    ]:
        srv = subprocess.Popen(["iperf3", "-s", "-1", "-p", "5210"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.3)  # let server bind
        try:
            r = run_bench(["iperf3", "-c", "127.0.0.1", "-p", "5210", "-t", "10", "-J"] + extra)
        finally:
            srv.terminate()  # no-op if -1 already let it exit; kills it if the client failed
            srv.wait()
        k, v = metric(json.loads(r.stdout)["end"])
        out[f"{name}.{k}"] = (v, "higher")
    return out

BENCHMARKS = {"net": {"needs": "iperf3", "fn": bench_net}}

if __name__ == "__main__":
    main(BENCHMARKS)
