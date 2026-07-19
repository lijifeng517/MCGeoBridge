import argparse
import json
import subprocess
from pathlib import Path


def run_smoke(root: Path, out_dir: Path, report_path: Path, timeout_sec: int):
    files = [
        p
        for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in (".inp", ".in")
    ]
    out_dir.mkdir(parents=True, exist_ok=True)

    results = []
    exe = Path(__file__).with_name("mcnp2gdml.py")
    for p in sorted(files):
        rel = p.relative_to(root)
        out = out_dir / (str(rel).replace("\\", "__").replace("/", "__") + ".gdml")
        cmd = ["python", str(exe), str(p), str(out)]
        try:
            cp = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec)
            ok = cp.returncode == 0
            err = ""
            if not ok:
                lines = (cp.stderr or cp.stdout or "").strip().splitlines()
                err = lines[-1] if lines else "unknown error"
            results.append({"file": str(rel), "ok": ok, "error": err})
        except subprocess.TimeoutExpired:
            results.append({"file": str(rel), "ok": False, "error": "timeout"})

    summary = {
        "total": len(results),
        "ok": sum(1 for r in results if r["ok"]),
        "fail": sum(1 for r in results if not r["ok"]),
    }
    by_error = {}
    for r in results:
        if r["ok"]:
            continue
        by_error[r["error"]] = by_error.get(r["error"], 0) + 1
    summary["top_errors"] = sorted(by_error.items(), key=lambda kv: kv[1], reverse=True)[:15]

    report = {"summary": summary, "results": results}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"[info] report written to {report_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run MCNP->GDML smoke conversion on a folder.")
    parser.add_argument("root", help="Root folder containing MCNP decks")
    parser.add_argument("--out-dir", default="out/engineering_smoke", help="Folder for generated GDML")
    parser.add_argument("--report", default="out/engineering_smoke_report.json", help="Output report JSON path")
    parser.add_argument("--timeout", type=int, default=25, help="Per-file conversion timeout in seconds")
    args = parser.parse_args()

    run_smoke(Path(args.root), Path(args.out_dir), Path(args.report), int(args.timeout))
