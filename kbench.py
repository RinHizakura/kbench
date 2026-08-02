#!/usr/bin/env python3
"""kbench — kernel regression benchmark runner.

    ./kbench.py run [bench...] [-o PLATFORM]   # append a run to data/PLATFORM.json (default: all but fio)
    ./kbench.py list [-o PLATFORM]             # list saved runs
    ./kbench.py rm <run> [-o PLATFORM]         # delete one run
"""
import json, os, re, shutil, statistics, subprocess, sys, time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PREFIX = "runs"  # -o overrides; data lands in data/<PREFIX>.json
NPROC = str(os.cpu_count() or 4)
REPEAT = 5  # iterations per benchmark, aggregated to mean+std

# Each bench_* returns {metric: (value, "higher"|"lower")}; aggregate() folds
# REPEAT of those into the stored {metric: {value, std, better}} form.

def run_bench(cmd, **kw):
    """Every benchmark command goes through here: print it, run it,
    raise on failure, return the finished process."""
    print("       " + " ".join(cmd), flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode:
        err = r.stderr.strip()
        raise RuntimeError(err.splitlines()[0] if err else f"{cmd[0]} exited {r.returncode}")
    return r

def parse(pattern, r, what):
    """First regex group of a finished command's output as float, or a readable error."""
    m = re.search(pattern, r.stdout + r.stderr)
    if not m:
        raise RuntimeError(f"could not parse {what} output")
    return float(m.group(1))

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

def bench_schbench():
    """Scheduler wakeup + request latency p50/p99/p99.9 + avg rps."""
    r = run_bench(["schbench", "-m", "2", "-t", NPROC, "-r", "30"])
    text = r.stdout + r.stderr  # schbench prints to stderr
    out = {}
    wake, _, req = text.partition("Request Latencies")  # old format: no marker -> req empty
    req = req.partition("RPS percentiles")[0]
    for prefix, block in (("", wake), ("req_", req)):
        for pct, val in re.findall(r"\*?\s*(\d+\.\d)th:\s+(\d+)", block):
            if pct in ("50.0", "99.0", "99.9") and f"{prefix}p{pct}_us" not in out:
                out[f"{prefix}p{pct}_us"] = (int(val), "lower")
    out["avg_rps"] = (parse(r"average rps:\s+([\d.]+)", r, "schbench rps"), "higher")
    return out

def bench_memory():
    """Memory bandwidth via sysbench (1M blocks)."""
    out = {}
    for op in ("read", "write"):
        r = run_bench(["sysbench", "memory", "--memory-block-size=1M",
                       "--memory-total-size=20G", f"--memory-oper={op}", "run"])
        out[f"{op}.bw_mibps"] = (parse(r"\(([\d.]+) MiB/sec\)", r, f"sysbench {op}"), "higher")
    return out

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

def _perf_usecs(*args):
    r = run_bench(["perf", "bench", *args])
    return {"usecs_op": (parse(r"([\d.]+) usecs/op", r, f"perf {args[0]}"), "lower")}

def bench_ipc():
    """Scheduler+IPC throughput, hackbench-style (perf bench sched messaging)."""
    r = run_bench(["perf", "bench", "sched", "messaging", "-g", "10", "-l", "1000"])
    return {"total_s": (parse(r"Total time:\s+([\d.]+)", r, "perf messaging"), "lower")}

def _stressng(stressor):
    """bogo ops/s (real time) for one stress-ng stressor, N workers x 15s."""
    r = run_bench(["stress-ng", f"--{stressor}", NPROC, "-t", "15", "--metrics-brief"])
    v = parse(rf"{stressor}\s+\d+\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+([\d.]+)",  # 5th col = bogo ops/s (real)
              r, f"stress-ng {stressor}")
    return {"bogo_ops_s": (v, "higher")}

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
    """REPEAT runs of {metric: (value, better)} -> {metric: {value, std, better}}."""
    out = {}
    for k in {k: None for r in runs for k in r}:  # ordered union of metric keys
        vals = [r[k][0] for r in runs if k in r]
        out[k] = {"value": round(statistics.mean(vals), 2),
                  "std": round(statistics.stdev(vals), 2) if len(vals) > 1 else 0,
                  "samples": [round(v, 2) for v in vals],
                  "better": next(r[k][1] for r in runs if k in r)}
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

def cmd_run(only=None):
    only = only or [n for n in BENCHMARKS if n != "fio"]  # fio only runs when asked explicitly
    result = {"sysinfo": sysinfo(), "benchmarks": {}, "skipped": {}}
    for name, b in BENCHMARKS.items():
        if only and name not in only:
            continue
        if not shutil.which(b["needs"]):
            result["skipped"][name] = f"'{b['needs']}' not installed"
            print(f"SKIP {name}: {b['needs']} not installed")
            continue
        t0 = time.time()
        try:
            runs = []
            for i in range(REPEAT):
                print(f"RUN  {name} ({i + 1}/{REPEAT}) ...", flush=True)
                runs.append(b["fn"]())
                print("     -> " + "  ".join(f"{k}={round(v, 2)}" for k, (v, _) in runs[-1].items()), flush=True)
            result["benchmarks"][name] = aggregate(runs)
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
    for flag in ("--output", "-o"):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                sys.exit(f"{flag} needs a value")
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
