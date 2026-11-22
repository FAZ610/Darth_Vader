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

The official scorer is deterministic for a bot identity, but `seed + salt` gives each variant a
different action draw. Run at least one independent block of 48 matches per variant rather than
comparing a single submission score. Keep only the entrypoint and profile that win by a consistent
margin in both squad and FFA observations.
