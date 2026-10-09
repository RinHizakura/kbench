#!/usr/bin/env python3
"""kbench — kernel regression benchmark runner.

    ./kbench.py run [bench...] [-o PLATFORM]   # append a run to data/PLATFORM/results.json (default: all but fio)
    ./kbench.py list [-o PLATFORM]             # list saved runs
    ./kbench.py rm <run> [-o PLATFORM]         # delete one run
"""
import gzip, hashlib, importlib.util, json, os, re, shutil, statistics, subprocess, sys, threading, time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PREFIX = "runs"  # -o overrides; data lands in data/<PREFIX>/
REPEAT = 5  # iterations per benchmark, aggregated to median+std

# Workloads live in workload/*.py; each exports BENCHMARKS = {name: {needs, fn[, repeat]}}
# where fn() returns {metric: (value, "higher"|"lower")}. aggregate() folds REPEAT of
# those into the stored {metric: {value, std, better}} form. Run a file directly to
# execute its benchmarks once without saving anything.
sys.path.insert(0, str(ROOT / "workload"))
BENCHMARKS = {}
for _f in sorted((ROOT / "workload").glob("*.py")):
    if _f.stem == "common":
        continue
    _spec = importlib.util.spec_from_file_location(_f.stem.replace("-", "_"), _f)
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    BENCHMARKS.update(_mod.BENCHMARKS)
from common import NPROC

def aggregate(runs):
    """REPEAT runs of {metric: (value, better)} -> {metric: {value, std, better}}."""
    out = {}
    for k in {k: None for r in runs for k in r}:  # ordered union of metric keys
        vals = [r[k][0] for r in runs if k in r]
        out[k] = {"value": round(statistics.median(vals), 2),
                  "std": round(statistics.stdev(vals), 2) if len(vals) > 1 else 0,
                  "samples": [round(v, 2) for v in vals],
                  "better": next(r[k][1] for r in runs if k in r)}
    return out

# --- sysinfo ---

def hwinfo():
    """Fixed hardware facts (don't change with the kernel): board model,
    cpu count, memory size, cache hierarchy. Rewritten on every run."""
    info = {"arch": os.uname().machine, "cpus": NPROC}
    for p in ("/proc/device-tree/model", "/sys/devices/virtual/dmi/id/product_name"):
        try:
            info["model"] = Path(p).read_bytes().decode().strip("\x00\n ")
            break
        except OSError:
            pass
    m = re.search(r"MemTotal:\s+(\d+)", Path("/proc/meminfo").read_text())
    info["mem_mib"] = round(int(m.group(1)) / 1024)
    caches = {}
    for idx in sorted(Path("/sys/devices/system/cpu/cpu0/cache").glob("index*")):
        try:
            rd = lambda f: (idx / f).read_text().strip()
            level = f"L{rd('level')}" + {"Data": "d", "Instruction": "i"}.get(rd("type"), "")
            caches[level] = f"{rd('size')} (cpus {rd('shared_cpu_list')})"
        except OSError:
            pass
    if caches:
        info["caches"] = caches
    return info

def kconfig():
    """Running kernel's config text, or None (needs CONFIG_IKCONFIG_PROC or /boot/config-*)."""
    try:
        return gzip.decompress(Path("/proc/config.gz").read_bytes()).decode()
    except OSError:
        pass
    try:
        return Path(f"/boot/config-{os.uname().release}").read_text()
    except OSError:
        return None

def soc_temp():
    """SoC temperature in °C, or None (no thermal zone)."""
    try:
        return round(int(Path("/sys/class/thermal/thermal_zone0/temp").read_text()) / 1000, 1)
    except (OSError, ValueError):
        return None

def cpu_freq_mhz():
    """Actual CPU clock in MHz. cpuinfo_cur_freq asks the driver (firmware clock on
    the RPi), so it shows firmware throttling the governor can't see. Root-only
    file; falls back to passwordless sudo, None if neither works."""
    p = "/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_cur_freq"
    try:
        return round(int(Path(p).read_text()) / 1000)
    except (OSError, ValueError):
        try:
            r = subprocess.run(["sudo", "-n", "cat", p], capture_output=True, text=True)
            return round(int(r.stdout) / 1000) if r.returncode == 0 else None
        except Exception:
            return None

def sampled(fn):
    """Run fn() while sampling SoC temp + actual clock every 10s in a thread.
    Returns (fn(), start_temp, max_temp, min_freq, max_freq) — start temp shows heat
    carried in from the previous rep/run, max temp the peak under load, min freq
    whether the firmware throttled mid-rep (< nominal means yes), max freq the
    clock actually reached. Sampler cost is one sysfs read (+ a sudo cat for the
    root-only freq file) per 10s — noise-level.
    """
    stop = threading.Event()
    temps, freqs = [], []
    def loop():
        while True:
            if (t := soc_temp()) is not None:
                temps.append(t)
            if (f := cpu_freq_mhz()) is not None:
                freqs.append(f)
            if stop.wait(10):
                return
    th = threading.Thread(target=loop, daemon=True)
    th.start()
    try:
        r = fn()
    finally:
        stop.set()
        th.join()
    return (r, temps[0] if temps else None, max(temps) if temps else None,
            min(freqs) if freqs else None, max(freqs) if freqs else None)

def cpu_busy(interval=3):
    """Fraction of all CPU time that was not idle over INTERVAL seconds (iowait counts
    as busy: disk DMA contends for the bus just like a core does)."""
    def snap():
        f = [int(x) for x in Path("/proc/stat").read_text().split("\n")[0].split()[1:]]
        return f[3], sum(f)  # idle, total
    i0, t0 = snap()
    time.sleep(interval)
    i1, t1 = snap()
    return 1 - (i1 - i0) / (t1 - t0)

def wait_quiet(max_busy=0.02, settle=2, timeout=900):
    """Block until the machine has been idle for SETTLE consecutive 3s windows.
    Returns the seconds spent waiting, 0 if every window passed (the settle windows
    themselves do not count); past TIMEOUT it warns and proceeds."""
    t0, ok, stalled = time.time(), 0, False
    while ok < settle:
        busy = cpu_busy()
        if busy <= max_busy:
            ok += 1
            continue
        ok, stalled = 0, True
        if time.time() - t0 > timeout:
            print(f"WARN machine still {busy:.0%} busy after {timeout}s, running anyway", flush=True)
            break
        print(f"WAIT machine {busy:.1%} busy (want <= {max_busy:.0%}), waiting...", flush=True)
        time.sleep(10)
    return round(time.time() - t0) if stalled else 0

def sysinfo():
    info = {"kernel": os.uname().release, "date": datetime.now().isoformat(timespec="seconds")}
    for name, path in [("cmdline", "/proc/cmdline"),
                       ("governor", "/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")]:
        try:
            info[name] = Path(path).read_text().strip()
        except OSError:
            pass
    if cfg := kconfig():
        h = hashlib.sha1(cfg.encode()).hexdigest()[:8]
        d = ROOT / "data" / PREFIX / "configs"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{h}.config").write_text(cfg)
        info["config"] = h
    return info

# --- storage: one dir per platform under data/ (results.json, hw.json, configs/) ---

def data_path():
    return ROOT / "data" / PREFIX / "results.json"

def load_data():
    return json.loads(data_path().read_text()) if data_path().exists() else {}

def save_data(data):
    data_path().parent.mkdir(parents=True, exist_ok=True)
    data_path().write_text(json.dumps(data, indent=2))  # indented: meant to be hand-editable

# --- commands ---

def cmd_run(only=None):
    only = only or [n for n in BENCHMARKS if n != "fio"]  # fio only runs when asked explicitly
    waited = wait_quiet()
    result = {"sysinfo": sysinfo(), "benchmarks": {}, "skipped": {}}
    if waited:
        result["sysinfo"]["quiet_wait_s"] = waited  # nonzero = something was running when we started
    for name, b in BENCHMARKS.items():
        if only and name not in only:
            continue
        if not shutil.which(b["needs"]):
            result["skipped"][name] = f"'{b['needs']}' not installed"
            print(f"SKIP {name}: {b['needs']} not installed")
            continue
        t0 = time.time()
        try:
            runs, temps, freqs = [], [], []
            repeat = b.get("repeat", REPEAT)
            for i in range(repeat):
                print(f"RUN  {name} ({i + 1}/{repeat}) ...", flush=True)
                r, tstart, tmax, fmin, fmax = sampled(b["fn"])
                runs.append(r)
                if tstart is not None:
                    temps.append([tstart, tmax])
                if fmin is not None:
                    freqs.append([fmin, fmax])
                print("     -> " + "  ".join(f"{k}={round(v, 2)}" for k, (v, _) in runs[-1].items()), flush=True)
            result["benchmarks"][name] = aggregate(runs)
            # per-rep [start, max] SoC temp + [min, max] actual clock, sampled every
            # 10s during the rep — correlates latency modes with heat / firmware throttling
            if temps:
                result.setdefault("temps_c", {})[name] = temps
            if freqs:
                result.setdefault("freqs_mhz", {})[name] = freqs
            print(f"     done in {time.time()-t0:.0f}s")
        except Exception as e:
            result["skipped"][name] = str(e)
            print(f"FAIL {name}: {e}")
    data = load_data()
    nums = [int(m.group(1)) for k in data if (m := re.search(r"_n(\d+)$", k))]
    run_name = f"{result['sysinfo']['kernel']}_n{max(nums, default=0) + 1}"
    data[run_name] = result
    save_data(data)
    (data_path().parent / "hw.json").write_text(json.dumps(hwinfo(), indent=2))
    print(f"\nsaved {run_name} in {data_path().relative_to(ROOT)}")
    pf = ROOT / "data" / "platforms.json"
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
