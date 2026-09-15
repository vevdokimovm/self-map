"""Snapshot of the Telegram-media-to-text campaign: elapsed time, tokens, files left.

Appends one row to 00-CAMPAIGN-METRICS.tsv. Tokens are read from the Claude Code
session logs (usage fields), counted only after the campaign start timestamp.
"""
import glob
import json
import os
from datetime import datetime, timezone

START = "2026-09-12T23:05:24Z"
LOGS = os.path.expanduser("~/.claude/projects/-Users-vasyaevdokimov-repos-self-map/*.jsonl")
ROOT = os.path.dirname(os.path.abspath(__file__))
IMPORTS = os.path.join(ROOT, "..", "..", "reports", "imports")
OUT = os.path.join(ROOT, "00-CAMPAIGN-METRICS.tsv")
KEYS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


def tokens_since(start: str) -> dict:
    total = dict.fromkeys(KEYS, 0)
    seen = set()
    for path in glob.glob(LOGS):
        for line in open(path, encoding="utf-8"):
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = rec.get("message") or {}
            usage = msg.get("usage")
            if not usage or rec.get("timestamp", "") < start:
                continue
            mid = msg.get("id")
            if mid in seen:
                continue
            seen.add(mid)
            for k in KEYS:
                total[k] += usage.get(k) or 0
    return total


def files_left() -> int:
    exts = (".jpg", ".jpeg", ".png", ".webp")
    return sum(1 for _, _, fs in os.walk(os.path.join(IMPORTS, "telegram-photos"))
               for f in fs if f.lower().endswith(exts))


def main() -> None:
    now = datetime.now(timezone.utc)
    start = datetime.fromisoformat(START.replace("Z", "+00:00"))
    t = tokens_since(START)
    row = [now.strftime("%Y-%m-%dT%H:%M:%SZ"), str(int((now - start).total_seconds())),
           str(files_left())] + [str(t[k]) for k in KEYS] + [str(sum(t.values()))]
    new = not os.path.exists(OUT)
    with open(OUT, "a", encoding="utf-8") as fh:
        if new:
            fh.write("utc\telapsed_s\tphotos_left\t" + "\t".join(KEYS) + "\ttotal\n")
        fh.write("\t".join(row) + "\n")
    print("\t".join(row))


if __name__ == "__main__":
    main()
