"""Block I/O: 4k rand r/w IOPS + p99 lat, 1M seq throughput, 4k fsync write."""
import json
from common import ROOT, run_bench, main

def bench_fio():
    """4k randread/randwrite + 1M seq r/w + 4k fsync on a temp file."""
    out = {}
    testfile = ROOT / ".fio-testfile"
    jobs = [
        ("randread-4k",  ["--rw=randread",  "--bs=4k", "--iodepth=32"]),
        ("randwrite-4k", ["--rw=randwrite", "--bs=4k", "--iodepth=32"]),
        ("seqread-1m",   ["--rw=read",      "--bs=1m", "--iodepth=8"]),
        ("seqwrite-1m",  ["--rw=write",     "--bs=1m", "--iodepth=8"]),
        ("syncwrite-4k", ["--rw=randwrite", "--bs=4k", "--iodepth=1", "--fsync=1"]),
    ]
    for name, extra in jobs:
        testfile.unlink(missing_ok=True)  # fresh file per job: no stale layout from a previous job/run
        r = run_bench(["fio", "--name", name, f"--filename={testfile}", "--size=1g",
                       "--runtime=30", "--time_based", "--ioengine=libaio", "--direct=1",
                       "--group_reporting", "--output-format=json"] + extra)
        side = json.loads(r.stdout)["jobs"][0]["write" if "write" in name else "read"]
        if name.startswith("seq"):
            out[f"{name}.bw_mbps"] = (side["bw_bytes"] / 1e6, "higher")
        else:
            out[f"{name}.iops"] = (side["iops"], "higher")
        out[f"{name}.p99_lat_us"] = (side["clat_ns"]["percentile"]["99.000000"] / 1000, "lower")
    testfile.unlink(missing_ok=True)
    return out

BENCHMARKS = {"fio": {"needs": "fio", "fn": bench_fio}}

if __name__ == "__main__":
    main(BENCHMARKS)
