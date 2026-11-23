"""
Sample GPU and CPU usage of the Ollama model runner while a benchmark runs.

    python3 TraceabilityApp/benchmark/common/resource_monitor.py OUT.csv [--interval 5]
    python3 TraceabilityApp/benchmark/common/resource_monitor.py --summary OUT.csv

Every interval it records:
- GPU utilisation, memory used/total (nvidia-smi);
- every GPU compute process (pid:user:MiB), so other users' jobs show up;
- the model(s) loaded in Ollama and their CPU/GPU split (`ollama ps`, e.g. "100% GPU");
- CPU% of the Ollama runner processes (from /proc deltas; 100% = one core).
Stops on SIGTERM / Ctrl+C. Standard library only.
"""

from __future__ import annotations

import argparse
import csv
import os
import pwd
import signal
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

FIELDS = ["time", "gpu_util_pct", "gpu_mem_used_mib", "gpu_mem_total_mib", "ollama_models",
          "ollama_processor", "runner_cpu_pct", "host_cpu_pct", "gpu_procs"]
TICK = os.sysconf("SC_CLK_TCK")


def _run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return ""


def gpu():
    out = _run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits"]).strip().splitlines()
    return [x.strip() for x in out[0].split(",")] if out else ["", "", ""]


def gpu_procs():
    rows = []
    for line in _run(["nvidia-smi", "--query-compute-apps=pid,used_memory",
                      "--format=csv,noheader,nounits"]).strip().splitlines():
        try:
            pid, mem = [x.strip() for x in line.split(",")]
            user = pwd.getpwuid(os.stat(f"/proc/{pid}").st_uid).pw_name
        except Exception:
            user = "?"
        rows.append(f"{pid}:{user}:{mem}")
    return " ".join(rows)


def ollama_ps():
    """[(name, processor)] from `ollama ps` (columns are separated by 2+ spaces)."""
    import re
    lines = _run(["ollama", "ps"]).strip().splitlines()
    if len(lines) < 2:
        return []
    head = lines[0]
    cols = [m.start() for m in re.finditer(r"\S+", head)]
    names = re.findall(r"\S+", head)
    i_proc = names.index("PROCESSOR") if "PROCESSOR" in names else None
    res = []
    for ln in lines[1:]:
        parts = re.split(r"\s{2,}", ln.strip())
        res.append((parts[0], parts[i_proc] if i_proc is not None and len(parts) > i_proc else "?"))
    return res


def runner_pids():
    """Ollama model-runner processes (llama-server / `ollama runner`), any user."""
    pids = []
    for d in Path("/proc").iterdir():
        if not d.name.isdigit():
            continue
        try:
            cmd = (d / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        except Exception:
            continue
        if "llama-server" in cmd or "ollama runner" in cmd or " runner --model" in cmd:
            pids.append(int(d.name))
    return pids


def proc_ticks(pid):
    try:
        f = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return int(f[11]) + int(f[12])          # utime + stime
    except Exception:
        return None


def host_ticks():
    f = [int(x) for x in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
    return sum(f), f[3] + f[4]                  # total, idle+iowait


def monitor(out: Path, interval: float) -> None:
    stop = False

    def _stop(*_):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    new = not out.exists()
    out.parent.mkdir(parents=True, exist_ok=True)
    prev_p, prev_h, prev_t = {}, host_ticks(), time.time()
    with out.open("a", newline="") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(FIELDS)
        while not stop:
            time.sleep(interval)
            now = time.time()
            dt = now - prev_t
            cur = {p: proc_ticks(p) for p in runner_pids()}
            used = sum((t - prev_p[p]) for p, t in cur.items() if t is not None and prev_p.get(p) is not None)
            runner_cpu = 100.0 * used / TICK / dt if dt > 0 else 0.0
            h = host_ticks()
            dtot, didle = h[0] - prev_h[0], h[1] - prev_h[1]
            host_cpu = 100.0 * (dtot - didle) / dtot if dtot else 0.0
            ps = ollama_ps()
            g = gpu()
            w.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), *g, ";".join(n for n, _ in ps),
                        ";".join(p for _, p in ps), f"{runner_cpu:.0f}", f"{host_cpu:.0f}", gpu_procs()])
            fh.flush()
            prev_p = {p: t for p, t in cur.items() if t is not None}
            prev_h, prev_t = h, now


def summary(path: Path) -> str:
    rows = list(csv.DictReader(path.open()))
    by = defaultdict(list)
    for r in rows:
        by[r["ollama_models"] or "(none loaded)"].append(r)
    lines = [f"{len(rows)} samples, {rows[0]['time'] if rows else ''} → {rows[-1]['time'] if rows else ''}", "",
             "| Loaded model | Samples | Processor (ollama ps) | GPU util avg / max | GPU mem max (MiB) "
             "| Runner CPU avg / max (%, 100 = 1 core) | Host CPU avg | Other users on GPU |",
             "|---|---|---|---|---|---|---|---|"]
    me = pwd.getpwuid(os.getuid()).pw_name
    for model, rs in by.items():
        def num(k):
            return [float(r[k]) for r in rs if r[k] not in ("", None)]
        gu, gm, rc, hc = num("gpu_util_pct"), num("gpu_mem_used_mib"), num("runner_cpu_pct"), num("host_cpu_pct")
        procs = sorted({r["ollama_processor"] for r in rs if r["ollama_processor"]}) or ["—"]
        others = sorted({p.split(":")[1] for r in rs for p in r["gpu_procs"].split()
                         if p.count(":") == 2 and p.split(":")[1] not in ("ollama", me)})
        avg = lambda v: sum(v) / len(v) if v else 0
        lines.append(f"| {model} | {len(rs)} | {', '.join(procs)} | {avg(gu):.0f}% / {max(gu, default=0):.0f}% | "
                     f"{max(gm, default=0):.0f} | {avg(rc):.0f} / {max(rc, default=0):.0f} | {avg(hc):.0f}% | "
                     f"{', '.join(others) or 'none'} |")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--interval", type=float, default=5.0)
    ap.add_argument("--summary", action="store_true")
    a = ap.parse_args()
    if a.summary:
        print(summary(Path(a.csv)))
    else:
        monitor(Path(a.csv), a.interval)


if __name__ == "__main__":
    sys.exit(main())
