#!/usr/bin/env python3
"""Download PLaMo 3 Translate Q4_K_M GGUF files. Standard library only.

Usage:
  python fetch-models.py --all --verify
  python fetch-models.py 0.8b 2b
  python fetch-models.py 8b --output-dir D:\\models

Downloads are resumable via a sibling ``.part`` file and are verified against
the size + SHA-256 recorded in models.json before being renamed into place.
"""
import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "models.json"
CHUNK = 1 << 20  # 1 MiB


def human(n):
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024 or unit == "GiB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def sha256_of(path):
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(entry, root, verify=True):
    dest = root / entry["folder"] / entry["file"]
    part = dest.with_name(dest.name + ".part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    expected_bytes = entry.get("bytes")
    expected_hash = entry.get("sha256") if verify else None

    if dest.exists():
        okay = (not expected_bytes or dest.stat().st_size == expected_bytes)
        if okay and expected_hash:
            okay = sha256_of(dest) == expected_hash
        if okay:
            print(f"[skip] {entry['size']}: already present and verified")
            return True
        print(f"[warn] {entry['size']}: existing file does not match manifest; replacing")
        dest.unlink()

    offset = part.stat().st_size if part.exists() else 0
    if expected_bytes and offset >= expected_bytes:
        offset = 0  # stale .part; start over

    headers = {"User-Agent": "plamo3-translate-local/1.0"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    req = urllib.request.Request(entry["url"], headers=headers)
    print(f"[get]  {entry['size']}: {entry['url']}"
          + (f" (resuming at {human(offset)})" if offset else ""))
    try:
        resp = urllib.request.urlopen(req, timeout=60)
    except Exception as exc:
        print(f"[fail] {entry['size']}: {exc}", file=sys.stderr)
        return False

    if resp.status == 200 and offset:
        offset = 0  # server ignored Range: restart from scratch
    digest = hashlib.sha256()
    if offset:
        with part.open("rb") as f:
            for chunk in iter(lambda: f.read(CHUNK), b""):
                digest.update(chunk)
    total = offset
    next_report = -1
    with resp, part.open("ab" if offset else "wb") as out:
        while True:
            try:
                chunk = resp.read(CHUNK)
            except Exception as exc:
                print(f"\n[fail] {entry['size']}: read error: {exc}", file=sys.stderr)
                return False
            if not chunk:
                break
            out.write(chunk)
            digest.update(chunk)
            total += len(chunk)
            pct = total * 100 // (expected_bytes or 1)
            if pct >= next_report + 10:
                next_report = pct
                print(f"\r  {human(total)}" + (f" / {human(expected_bytes)} ({pct}%)" if expected_bytes else ""),
                      end="", flush=True)
    print()

    actual = digest.hexdigest()
    problems = []
    if expected_bytes and total != expected_bytes:
        problems.append(f"size {total} != expected {expected_bytes}")
    if expected_hash and actual != expected_hash:
        problems.append(f"SHA-256 {actual} != expected {expected_hash}")
    if problems:
        print(f"[fail] {entry['size']}: " + "; ".join(problems)
              + f". Kept {part} for inspection.", file=sys.stderr)
        return False
    part.replace(dest)
    print(f"[ok]   {entry['size']}: {dest} ({human(total)}, sha256 {actual[:12]}...)")
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sizes", nargs="*", choices=["0.8b", "2b", "8b"],
                    help="which models to download (default: all)")
    ap.add_argument("--all", action="store_true", help="download all three models")
    ap.add_argument("--output-dir", default=str(HERE), help="repo root (default: this script's directory)")
    ap.add_argument("--no-verify", action="store_true", help="skip size/hash checks after download")
    args = ap.parse_args()

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    sizes = [m["size"] for m in manifest["models"]] if (args.all or not args.sizes) else args.sizes
    wanted = [m for m in manifest["models"] if m["size"] in sizes]
    if not wanted:
        ap.error("no models selected")

    failed = [m["size"] for m in wanted if not fetch(m, Path(args.output_dir), not args.no_verify)]
    if failed:
        print("Failed: " + ", ".join(failed), file=sys.stderr)
        raise SystemExit(1)
    print("Done. Start the service with: .\\start-plamo.bat   (or: python manager.py)")


if __name__ == "__main__":
    main()
