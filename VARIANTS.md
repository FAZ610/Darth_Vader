# t800 strategy variants

These variants share the `t8core.py` implementation and change only profile parameters.
Submit one entrypoint at a time by changing `ENTRYPOINT` in `Dockerfile`.

| Variant | Hypothesis | Main changes |
|---|---|---|
| `t801.py` | Cube snowballing and loot races improve squad and FFA results | Longer cube/drop/crate hunting, more fight-time cube grabs |
| `t802.py` | Hiding earlier is better after the real practice zone starts collapsing | Ghost mode begins at 240 m instead of 140 m |
| `t803.py` | Retreating more often avoids low-health trades | Higher retreat threshold, stronger crowd/lose-rule behavior |
| `t804.py` | A longer laser stick and aggressive finisher convert wins better | 280 m laser seeking, 32 m finish range, target sticking and rear bonuses |
| `t805.py` | Once FFA is detected, wider survival bubbles and calmer looting improve placement | 220 m bubble, larger hiding preference, lower loot/contest aggression |

## 801 follow-ups

Observed practice scores:

| Variant | Score |
|---|---:|
| `t800` | 5.29 |
| `t801` | 5.53 |
| `t802` | 5.23 |
| `t803` | 5.16 |
| `t804` | 5.30 |

Because `t801` is the only meaningful improvement, its follow-ups vary only nearby cube, drop,
and finish behavior:

| Variant | Hypothesis | Main changes |
|---|---|---|
| `t806.py` | Stronger fight-time cube collection is the next useful gain | 130 m fight cube grab, longer crate farming |
| `t807.py` | A wider drop search adds safe late cubes without changing combat | 300 m drop search |
| `t808.py` | Combining cube snowballing with laser finishing may compound gains | `t801` profile plus tighter target stick and finisher settings |
| `t809.py` | A slightly lower farming threshold keeps cube hunting more often while healthy | FarmHP 0.25 instead of 0.35 |

The official scorer is deterministic for a bot identity, but `seed + salt` gives each variant a
different action draw. Run at least one independent block of 48 matches per variant rather than
comparing a single submission score. Keep only the entrypoint and profile that win by a consistent
margin in both squad and FFA observations.
