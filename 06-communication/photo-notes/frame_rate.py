"""Registry of processing speed: seconds per frame, measured between calls.

Reads the current total of documented frames from every telegram-*-photos.md
(the "Прочитано | N / M" line of the quality passport) and compares it with the
previous row of 00-FRAME-RATE.tsv. Each call appends one row.

Usage:
    python3 frame_rate.py                # measure and append
    python3 frame_rate.py --note "..."   # same, with a label for the interval
"""
import argparse
import glob
import os
import re
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "00-FRAME-RATE.tsv")
NOTES = os.path.join(ROOT, "telegram-*-photos.md")
HEADER = "utc\tdone\ttotal\td_frames\td_seconds\tsec_per_frame\tnote\n"
DONE_RE = re.compile(r"\*\*Прочитано\*\*\s*\|\s*(\d+)\s*/\s*(\d+)")


def frames_done() -> tuple[int, int]:
    """Sum documented and total frames across all per-chat note files."""
    done = total = 0
    for path in glob.glob(NOTES):
        with open(path, encoding="utf-8") as fh:
            matches = DONE_RE.findall(fh.read())
        if matches:
            d, t = matches[-1]
            done += int(d)
            total += int(t)
    return done, total


def previous_row() -> tuple[datetime, int] | None:
    if not os.path.exists(OUT):
        return None
    with open(OUT, encoding="utf-8") as fh:
        rows = [line.rstrip("\n").split("\t") for line in fh if line.strip()]
    if len(rows) < 2:
        return None
    last = rows[-1]
    return datetime.fromisoformat(last[0].replace("Z", "+00:00")), int(last[1])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--note", default="")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    done, total = frames_done()
    prev = previous_row()
    if prev is None:
        d_frames = d_seconds = 0
        rate = ""
    else:
        prev_time, prev_done = prev
        d_frames = done - prev_done
        d_seconds = int((now - prev_time).total_seconds())
        rate = f"{d_seconds / d_frames:.1f}" if d_frames > 0 else ""

    row = [now.strftime("%Y-%m-%dT%H:%M:%SZ"), str(done), str(total),
           str(d_frames), str(d_seconds), rate, args.note]
    new = not os.path.exists(OUT)
    with open(OUT, "a", encoding="utf-8") as fh:
        if new:
            fh.write(HEADER)
        fh.write("\t".join(row) + "\n")
    print("\t".join(row))


if __name__ == "__main__":
    main()
