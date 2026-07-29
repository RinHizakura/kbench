#!/usr/bin/env python3
"""kbench — kernel regression benchmark runner.

    ./kbench.py run    # run all available benchmarks -> runs/<kernel>_nN/ containing
                       # result.json, index.html, vs_baseline.html, vs_prev.html
                       # (delete a run by deleting its folder)

Add a benchmark: one entry in BENCHMARKS. Metric convention:
"higher" metrics are throughput-like, "lower" are latency-like.
"""
import json, os, re, shutil, subprocess, sys, time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RUNS = ROOT / "runs"
REGRESSION_PCT = 5.0  # flag if worse than baseline by this much

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

def bench_rtla():
    """Timer IRQ/thread wakeup latency via rtla timerlat. Metrics: avg/max (usec). Needs root."""
    r = run(["rtla", "timerlat", "top", "-d", "30", "-q"])
    if r.returncode:
        raise RuntimeError((r.stderr.strip() or "rtla failed") + " (needs root?)")
    irq_max, thr_max, thr_avgs = 0.0, 0.0, []
    for line in r.stdout.splitlines():
        parts = line.split("|")
        if len(parts) == 3 and re.match(r"\s*\d+\s+#", parts[0]):  # per-CPU rows only
            irq = [float(x) for x in parts[1].split()]
            thr = [float(x) for x in parts[2].split()]
            irq_max = max(irq_max, irq[-1])
            thr_max = max(thr_max, thr[-1])
            thr_avgs.append(thr[-2])
    if not thr_avgs:
        raise RuntimeError("could not parse rtla output")
    return {
        "irq_max_us":    {"value": irq_max, "better": "lower"},
        "thread_avg_us": {"value": round(sum(thr_avgs) / len(thr_avgs), 1), "better": "lower"},
        "thread_max_us": {"value": thr_max, "better": "lower"},
    }

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
    """Kernel net stack over loopback via iperf3. Metrics: TCP Gbps, 64B-UDP pps."""
    out = {}
    for name, extra, metric in [
        ("tcp",     [],                            lambda e: ("bw_gbps", round(e["sum_received"]["bits_per_second"] / 1e9, 2))),
        ("udp-64b", ["-u", "-b", "0", "-l", "64"], lambda e: ("pps", round(e["sum"]["packets"] / e["sum"]["seconds"]))),
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

BENCHMARKS = {
    "fio":      {"needs": "fio",      "fn": bench_fio},
    "schbench": {"needs": "schbench", "fn": bench_schbench},
    "rtla":     {"needs": "rtla",     "fn": bench_rtla},
    "memory":   {"needs": "sysbench", "fn": bench_memory},
    "net":      {"needs": "iperf3",   "fn": bench_net},
}

# ---------------------------------------------------------------- sysinfo

def sysinfo():
    info = {"kernel": os.uname().release, "date": datetime.now().isoformat(timespec="seconds")}
    for name, path in [("cmdline", "/proc/cmdline"),
                       ("governor", "/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")]:
        try:
            info[name] = Path(path).read_text().strip()
        except OSError:
            pass
    return info

# ---------------------------------------------------------------- run

def cmd_run(only=None):
    result = {"sysinfo": sysinfo(), "benchmarks": {}, "skipped": {}}
    for name, b in BENCHMARKS.items():
        if only and name not in only:
            continue
        if not shutil.which(b["needs"]):
            result["skipped"][name] = f"'{b['needs']}' not installed"
            print(f"SKIP {name}: {b['needs']} not installed")
            continue
        print(f"RUN  {name} ...", flush=True)
        t0 = time.time()
        try:
            result["benchmarks"][name] = b["fn"]()
            print(f"     done in {time.time()-t0:.0f}s")
        except Exception as e:
            result["skipped"][name] = str(e)
            print(f"FAIL {name}: {e}")
    nums = [int(m.group(1)) for d in RUNS.glob("*") if (m := re.search(r"_n(\d+)$", d.name))]
    rundir = RUNS / f"{result['sysinfo']['kernel']}_n{max(nums, default=0) + 1}"
    rundir.mkdir(parents=True)
    (rundir / "result.json").write_text(json.dumps(result, indent=2))
    print(f"\nsaved {rundir}/result.json")
    gen_html(rundir.name)
    return result

# ---------------------------------------------------------------- html

def gen_html(cur):
    data = {f.parent.name: json.loads(f.read_text()) for f in RUNS.glob("*/result.json")}
    runs = sorted(data, key=lambda r: data[r]["sysinfo"]["date"])  # chronological
    tmpl = ((ROOT / "template.html").read_text()
            .replace("__DATA__", json.dumps(data))
            .replace("__THRESHOLD__", str(REGRESSION_PCT)))

    def emit(name, base):
        (RUNS / cur / name).write_text(tmpl.replace("__INIT__", json.dumps({"cur": cur, "base": base})))
        print(f"wrote runs/{cur}/{name}")

    emit("index.html", "")
    i = runs.index(cur)
    if i > 0:
        emit("vs_baseline.html", runs[0])  # ponytail: baseline = oldest run
        emit("vs_prev.html", runs[i - 1])

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] == "run":
        cmd_run(only=args[1:] or None)
    else:
        sys.exit(__doc__)
