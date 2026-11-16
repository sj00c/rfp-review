#!/usr/bin/env python3
import argparse
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("start", nargs="?", type=int, default=1)
    ap.add_argument("--max-bytes", type=int, default=8000)
    a = ap.parse_args()
    with open(a.file, encoding="utf-8") as fp:
        lines = fp.read().splitlines()
    used, i = 0, max(a.start, 1)
    while i <= len(lines):
        row = f"{i}\t{lines[i - 1]}"
        cost = len(row.encode("utf-8")) + 1
        if used and used + cost > a.max_bytes:
            break
        print(row if cost <= a.max_bytes else row[: a.max_bytes // 3] + " …(line cut)")
        used += cost
        i += 1
    if i <= len(lines):
        print(f"[next: {i} of {len(lines)}]")
    else:
        print(f"[end of file: {len(lines)} lines]")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
