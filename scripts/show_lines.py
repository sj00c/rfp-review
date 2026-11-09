#!/usr/bin/env python3
"""Print a line range of a UTF-8 text file with line numbers, never more than --max-bytes.

Harness shells silently truncate long output (often ~10KB). Korean text is 3 bytes per character,
so a fixed line count is not safe; this stops at a byte budget and prints where to continue.

Usage: python show_lines.py extracted/제안요청서.txt 1          # from line 1 until the budget
       python show_lines.py extracted/제안요청서.txt 1 120      # at most lines 1-120
       python show_lines.py extracted/제안요청서.txt --count
"""
import argparse
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("start", nargs="?", type=int, default=1)
    ap.add_argument("end", nargs="?", type=int)
    ap.add_argument("--max-bytes", type=int, default=8000)
    ap.add_argument("--count", action="store_true", help="print line and byte counts only")
    a = ap.parse_args()
    with open(a.file, encoding="utf-8") as fp:
        lines = fp.read().splitlines()
    if a.count:
        size = sum(len(x.encode("utf-8")) + 1 for x in lines)
        print(f"{a.file}: {len(lines)} lines, {size:,} bytes (~{size // a.max_bytes + 1} reads)")
        return 0
    end = min(a.end or len(lines), len(lines))
    used, i = 0, max(a.start, 1)
    while i <= end:
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
