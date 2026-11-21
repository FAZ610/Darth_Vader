"""Paired tournament: every match holds the control, 3 candidates and a fixed opponent pool.

    python lab/tourney.py --tag r1 --control t200 --pool hunter:6 t100:3 baseline_bot:3 \
        --candidates v_engage150 v_nocover ... --rounds 40

Each candidate's score is its points minus the control's points in the same matches (paired),
so match-to-match luck mostly cancels. Results append to lab/RESULTS.md and lab/results/<tag>.json.
"""
import argparse
import json
import math
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

LAB = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(LAB)
sys.path.insert(0, ROOT)
import local_arena  # noqa: E402


def resolve(name):
    for p in (os.path.join(LAB, "bots", name + ".py"), os.path.join(ROOT, name + ".py"), name):
        if os.path.isfile(p):
            return os.path.abspath(p)
    sys.exit("no bot named %s" % name)


def parse_counts(specs):
    out = []
    for s in specs:
        name, _, n = s.partition(":")
        out += [name] * int(n or 1)
    return out


def schedule(cands, per_match, rounds):
    """Each round places every candidate exactly once, per_match at a time."""
    matches = []
    for r in range(rounds):
        order = cands[r % len(cands):] + cands[:r % len(cands)]
        for k in range(0, len(order), per_match):
            group = order[k:k + per_match]
            while len(group) < per_match:  # pad with already-placed ones
                group.append(order[(k + len(group)) % len(order)])
            matches.append(group)
    return matches


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--control", default="t200")
    ap.add_argument("--pool", nargs="+", default=["hunter:12"])
    ap.add_argument("--candidates", nargs="+", required=True)
    ap.add_argument("--per-match", type=int, default=3)
    ap.add_argument("--rounds", type=int, default=30, help="matches per candidate")
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--seed", type=int, default=50000)
    ap.add_argument("--budget-ms", type=float, default=80.0)
    a = ap.parse_args()

    pool = parse_counts(a.pool)
    groups = schedule(a.candidates, a.per_match, a.rounds)
    jobs = []
    for i, g in enumerate(groups):
        lineup = [("CONTROL", resolve(a.control))] + [(c, resolve(c)) for c in g] + [("pool:" + p, resolve(p)) for p in pool]
        assert len(lineup) <= 16, len(lineup)
        jobs.append((lineup, a.seed + i))
    print("%s: %d matches, %d candidates x %d each, control=%s, pool=%s" % (
        a.tag, len(jobs), len(a.candidates), a.rounds, a.control, " ".join(a.pool)), flush=True)
    t0 = time.perf_counter()
    results = []
    with ProcessPoolExecutor(max_workers=a.jobs) as ex:
        futs = [ex.submit(local_arena.run_match, lu, sd, a.budget_ms, None, None, False) for lu, sd in jobs]
        for k, f in enumerate(as_completed(futs)):
            results.append(f.result())
            if (k + 1) % 10 == 0:
                print("  %d/%d matches (%.0fs)" % (k + 1, len(jobs), time.perf_counter() - t0), flush=True)

    stats = {}
    for res in results:
        ctrl = [m["points"] for m in res["mechs"] if m["label"] == "CONTROL"][0]
        for m in res["mechs"]:
            s = stats.setdefault(m["label"], {"pts": [], "diff": [], "surv": [], "kills": [], "zone": 0})
            s["pts"].append(m["points"])
            s["surv"].append(m["death_t"] if m["death_t"] is not None else res["duration"])
            s["kills"].append(m["kills"])
            s["zone"] += m["cause"] == "zone"
            if m["label"] != "CONTROL" and not m["label"].startswith("pool:"):
                s["diff"].append(m["points"] - ctrl)

    def mean(x):
        return sum(x) / len(x) if x else float("nan")

    def se(x):
        if len(x) < 2:
            return float("nan")
        mu = mean(x)
        return math.sqrt(sum((v - mu) ** 2 for v in x) / (len(x) - 1) / len(x))

    rows = []
    for label, s in stats.items():
        rows.append((label, len(s["pts"]), mean(s["pts"]), mean(s["diff"]), se(s["diff"]),
                     mean(s["surv"]), mean(s["kills"]), 100.0 * s["zone"] / len(s["pts"])))
    rows.sort(key=lambda r: (r[0].startswith("pool:"), r[0] != "CONTROL", -(r[3] if r[3] == r[3] else -99)))
    lines = ["", "## %s  (%s)" % (a.tag, time.strftime("%Y-%m-%d %H:%M")),
             "control=%s, pool=%s, %d matches, %.0f s" % (a.control, " ".join(a.pool), len(results), time.perf_counter() - t0),
             "", "| bot | n | points | vs control | +-SE | surv s | kills | zone deaths % |", "|---|---|---|---|---|---|---|---|"]
    for label, n, pts, d, e, surv, k, z in rows:
        dd = "" if d != d else "%+.2f" % d
        ee = "" if e != e else "%.2f" % e
        lines.append("| %s | %d | %.2f | %s | %s | %.0f | %.2f | %.0f |" % (label, n, pts, dd, ee, surv, k, z))
    text = "\n".join(lines)
    print(text)
    with open(os.path.join(LAB, "RESULTS.md"), "a", encoding="utf-8") as fh:
        fh.write(text + "\n")
    os.makedirs(os.path.join(LAB, "results"), exist_ok=True)
    with open(os.path.join(LAB, "results", a.tag + ".json"), "w", encoding="utf-8") as fh:
        json.dump({"args": vars(a), "results": results}, fh)


if __name__ == "__main__":
    main()
