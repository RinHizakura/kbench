#!/usr/bin/env python3
"""kbench — kernel regression benchmark runner.

    ./kbench.py run [bench...] [--output PLATFORM]   # append a run to data/PLATFORM.json
    ./kbench.py list [--output PLATFORM]             # list saved runs
    ./kbench.py rm <run> [--output PLATFORM]         # delete one run
"""
import json, os, re, shutil, statistics, subprocess, sys, time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PREFIX = "runs"  # --output overrides; data lands in data/<PREFIX>.json

# ---------------------------------------------------------------- runners

def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)

def bench_fio():
    """4k randread/randwrite + 1M seqread on a temp file. Metrics: IOPS, p99 lat."""
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
        r = run(["fio", "--name", name, f"--filename={testfile}", "--size=1g",
                 "--runtime=30", "--time_based", "--ioengine=libaio", "--direct=1",
                 "--group_reporting", "--output-format=json"] + extra)
        j = json.loads(r.stdout)["jobs"][0]
        side = j["write"] if "write" in name else j["read"]
        if name.startswith("seq"):
            out[f"{name}.bw_mbps"] = {"value": round(side["bw_bytes"] / 1e6, 1), "better": "higher"}
        else:
            out[f"{name}.iops"] = {"value": round(side["iops"], 1), "better": "higher"}
        p99 = side["clat_ns"]["percentile"]["99.000000"] / 1000
        out[f"{name}.p99_lat_us"] = {"value": round(p99, 1), "better": "lower"}
    testfile.unlink(missing_ok=True)
    return out

def bench_schbench():
    """Scheduler wakeup latency. Metrics: p50/p99/p99.9 (usec)."""
    n = os.cpu_count() or 4
    r = run(["schbench", "-m", "2", "-t", str(n), "-r", "30"])
    text = r.stdout + r.stderr  # schbench prints to stderr
    out = {}
    # matches both old ("50.0th: 45") and new ("* 50.0th: 45") formats
    for pct, val in re.findall(r"\*?\s*(\d+\.\d)th:\s+(\d+)", text):
        if pct in ("50.0", "99.0", "99.9") and f"p{pct}_us" not in out:
            out[f"p{pct}_us"] = {"value": int(val), "better": "lower"}
    rps = re.search(r"average rps:\s+([\d.]+)", text)
    if rps:
        out["avg_rps"] = {"value": float(rps.group(1)), "better": "higher"}
    return out

def bench_memory():
    """Memory bandwidth via sysbench (1M blocks). Metrics: MiB/s read/write."""
    out = {}
    for op in ("read", "write"):
        r = run(["sysbench", "memory", "--memory-block-size=1M",
                 "--memory-total-size=20G", f"--memory-oper={op}", "run"])
        m = re.search(r"\(([\d.]+) MiB/sec\)", r.stdout)
        if not m:
            raise RuntimeError(f"could not parse sysbench {op} output")
        out[f"{op}.bw_mibps"] = {"value": float(m.group(1)), "better": "higher"}
    return out

def bench_net():
    """Kernel net stack over loopback via iperf3.
    Metrics: TCP Gbps (plain + zero-copy), 64B-UDP pps (1 + N streams)."""
    bw = lambda e: ("bw_gbps", round(e["sum_received"]["bits_per_second"] / 1e9, 2))
    pps = lambda e: ("pps", round(e["sum"]["packets"] / e["sum"]["seconds"]))
    udp = ["-u", "-b", "0", "-l", "64"]
    nstreams = str(os.cpu_count() or 4)
    out = {}
    for name, extra, metric in [
        ("tcp",           [],                      bw),
        ("tcp-zc",        ["-Z"],                  bw),   # zero-copy (sendfile) send path
        ("udp-64b",       udp,                     pps),
        ("udp-64b-multi", udp + ["-P", nstreams],  pps),
    ]:
        srv = subprocess.Popen(["iperf3", "-s", "-1", "-p", "5210"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.3)  # let server bind
        r = run(["iperf3", "-c", "127.0.0.1", "-p", "5210", "-t", "10", "-J"] + extra)
        srv.wait()
        if r.returncode:
            raise RuntimeError(r.stderr.strip() or "iperf3 failed")
        k, v = metric(json.loads(r.stdout)["end"])
        out[f"{name}.{k}"] = {"value": v, "better": "higher"}
    return out

def _perf(*args):
    """Run perf bench, return its text output."""
    r = run(["perf", "bench", *args])
    if r.returncode:  # ubuntu wrapper exists but real perf may be missing for this kernel
        raise RuntimeError(r.stderr.strip().splitlines()[0] if r.stderr.strip() else "perf failed")
    return r.stdout + r.stderr

def _perf_usecs(*args):
    m = re.search(r"([\d.]+) usecs/op", _perf(*args))
    if not m:
        raise RuntimeError(f"could not parse perf bench {' '.join(args)}")
    return {"usecs_op": {"value": float(m.group(1)), "better": "lower"}}

def bench_ipc():
    """Scheduler+IPC throughput, hackbench-style (perf bench sched messaging)."""
    m = re.search(r"Total time:\s+([\d.]+)", _perf("sched", "messaging", "-g", "10", "-l", "1000"))
    if not m:
        raise RuntimeError("could not parse perf bench messaging")
    return {"total_s": {"value": float(m.group(1)), "better": "lower"}}

def _stressng(stressor):
    """bogo ops/s (real time) for one stress-ng stressor, N workers x 15s."""
    r = run(["stress-ng", f"--{stressor}", str(os.cpu_count() or 4), "-t", "15", "--metrics-brief"])
    m = re.search(rf"{stressor}\s+\d+\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+([\d.]+)",
                  r.stdout + r.stderr)  # 5th col = bogo ops/s (real time)
    if not m:
        raise RuntimeError(f"could not parse stress-ng {stressor}")
    return {"bogo_ops_s": {"value": float(m.group(1)), "better": "higher"}}

BENCHMARKS = {
    "fio":        {"needs": "fio",       "fn": bench_fio},
    "schbench":   {"needs": "schbench",  "fn": bench_schbench},
    "memory":     {"needs": "sysbench",  "fn": bench_memory},
    "net":        {"needs": "iperf3",    "fn": bench_net},
    "syscall":    {"needs": "perf",      "fn": lambda: _perf_usecs("syscall", "basic")},
    "perf-sched": {"needs": "perf",      "fn": lambda: _perf_usecs("sched", "pipe")},
    "ipc":        {"needs": "perf",      "fn": bench_ipc},
    "pagefault":  {"needs": "stress-ng", "fn": lambda: _stressng("fault")},
    "fork":       {"needs": "stress-ng", "fn": lambda: _stressng("fork")},
}

def aggregate(runs):
    """Merge repeated runs of one benchmark into mean + std per metric."""
    out = {}
    for k in {k: None for r in runs for k in r}:  # ordered union of metric keys
        vals = [r[k]["value"] for r in runs if k in r]
        out[k] = {"value": round(statistics.mean(vals), 2),
                  "std": round(statistics.stdev(vals), 2) if len(vals) > 1 else 0,
                  "better": next(r[k]["better"] for r in runs if k in r)}
    return out

# --- sysinfo ---

def sysinfo():
    info = {"kernel": os.uname().release, "date": datetime.now().isoformat(timespec="seconds")}
    for name, path in [("cmdline", "/proc/cmdline"),
                       ("governor", "/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")]:
        try:
            info[name] = Path(path).read_text().strip()
        except OSError:
            pass
    return info

# --- storage: one json per platform under data/, keyed by run name ---

def data_path():
    return ROOT / "data" / f"{PREFIX}.json"

def load_data():
    return json.loads(data_path().read_text()) if data_path().exists() else {}

def save_data(data):
    data_path().parent.mkdir(exist_ok=True)
    data_path().write_text(json.dumps(data, indent=2))  # indented: meant to be hand-editable

# --- commands ---

REPEAT = 5  # iterations per benchmark, aggregated to mean+std

def cmd_run(only=None):
    result = {"sysinfo": sysinfo(), "benchmarks": {}, "skipped": {}}
    for name, b in BENCHMARKS.items():
        if only and name not in only:
            continue
        if not shutil.which(b["needs"]):
            result["skipped"][name] = f"'{b['needs']}' not installed"
            print(f"SKIP {name}: {b['needs']} not installed")
            continue
        print(f"RUN  {name} x{REPEAT} ...", flush=True)
        t0 = time.time()
        try:
            result["benchmarks"][name] = aggregate([b["fn"]() for _ in range(REPEAT)])
            print(f"     done in {time.time()-t0:.0f}s")
        except Exception as e:
            result["skipped"][name] = str(e)
            print(f"FAIL {name}: {e}")
    data = load_data()
    nums = [int(m.group(1)) for k in data if (m := re.search(r"_n(\d+)$", k))]
    run_name = f"{result['sysinfo']['kernel']}_n{max(nums, default=0) + 1}"
    data[run_name] = result
    save_data(data)
    print(f"\nsaved {run_name} in {data_path().relative_to(ROOT)}")
    pf = data_path().parent / "platforms.json"
    plats = json.loads(pf.read_text()) if pf.exists() else []
    if PREFIX not in plats:
        pf.write_text(json.dumps(sorted(plats + [PREFIX])))
        print("updated platforms.json")
    return result

if __name__ == "__main__":
    args = sys.argv[1:]
    if "--output" in args:
        i = args.index("--output")
        if i + 1 >= len(args):
            sys.exit("--output needs a value")
        PREFIX = args[i + 1]
        del args[i:i + 2]
    if not args or args[0] == "run":
        cmd_run(only=args[1:] or None)
    elif args[0] == "list":
        for run_name, r in sorted(load_data().items(), key=lambda kv: kv[1]["sysinfo"]["date"]):
            print(run_name, r["sysinfo"]["date"])
    elif args[0] == "rm" and len(args) == 2:
        data = load_data()
        if args[1] not in data:
            sys.exit(f"no run '{args[1]}' in {data_path().name} (see: kbench.py list)")
        del data[args[1]]
        save_data(data)
        print(f"removed {args[1]} from {data_path().name}")
    else:
        sys.exit(__doc__)
