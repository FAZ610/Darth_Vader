# t300 experiment notes (2026-11-21)

**Goal.** Improve on t200, which has a real score of 3.92. t201 ("avoid fights") scored only 2.56 for real.

**Method.** [t3core.py](../t3core.py) is t200 with every behaviour behind a parameter. Its defaults make
the same decisions as t200 on all 300 recorded observations. [variants.py](variants.py) generates one
bot per variant, and [tourney.py](tourney.py) runs paired matches. Each match holds a t200 control,
3 candidates and a pool of 8 `hunter` + 4 `t200`. A candidate's score is its points minus the
control's points in the same match. The full tables are in [RESULTS.md](RESULTS.md).

**Calibration caveat.** No local opponent pool reproduced the real t200 > t201 ordering: t201 wins
locally every time. The real scores are also noisy, about ±0.65 each over 48 matches. So local
wins are a shortlist, not proof. Anything resembling t201's "hide from watchers" was excluded from
merging.

## What helped (kept in t300)
| change | r1 | r2 | r3 (in combination) |
|---|---|---|---|
| hold near the edge of the safe disc (`drift_frac` 0.95) | +1.65 | +0.47 | |
| hunt NPC drones when healthy (`npc_farm`) | +0.98 | +0.50 | |
| edge + farm + damage-first upgrades (**t300**) | | **+1.43** | **+1.19** |
| edge + farm + kite 80 m (runner-up) | | | +0.89 |

## Looked good once, did not repeat (dropped)
- damage-first upgrades on their own: +0.91, then -0.97. They only help together with farming (more cubes).
- smaller zone margin: +1.13, then -0.45, with 5% zone deaths in a combination.
- drift to the centre: +1.20, then -0.77.

## Clearly worse (avoid)
- aggressive brawler style -2.37; only shooting within 50 m -1.55; preferring the mortar -1.30
- chase targets -0.81; never take cover -0.81; long-range laser sniper -0.85; back off early -0.87

## Untested / next ideas
- t300 + kite 80 m together (each was positive on its own)
- real submissions are the only ground truth: compare t300's real score with t200's 3.92

# Round 4 setup: a tougher, calibrated simulator (2026-11-22)

**Real result.** t300 scored 3.83 for real, a tie with t200's 3.92 (each about ±0.65). So the
earlier pool (8 hunters + 4 t200) was not a good proxy either.

**New simulator options** in [local_arena.py](../local_arena.py). Each pool entry can carry perks:
- `hp`, `dmg`: multipliers on max HP and on damage dealt
- `spread`: multiplier on gun spread
- `cubes`: cubes at the start
- `hunt`: hunters cannot see each other, so they only fight the bots under test

Pool syntax is `elite:9@hunt=1`. `elite` is a new strong opponent: it loots and farms early,
takes damage upgrades, picks off weakened mechs and holds laser range.

**Calibration** (t200 as control; t300, t201 and baseline as candidates; 30 matches per row):

| pool | t200 | t300 | t201 | baseline |
|---|---|---|---|---|
| **real** | **3.92** | **3.83** | **2.56** | **2.21** |
| elite x12 (+ cubes/HP/damage perks, 4 variants) | 6.9-8.1 | 8.5-9.5 | 8.8-9.4 | 6.7-7.8 |
| elite x12, all hunting | 2.00 | 2.20 | 2.07 | 0.87 |
| 6 hunting + 6 normal | 5.43 | 6.57 | 6.27 | 3.57 |
| 3 hunting + 9 normal | 7.57 | 10.03 | 8.30 | 4.30 |

Stronger opponents alone never pull our bots down; hunting opponents do. The round 4 pool is
9 hunting elites + 3 normal elites, interpolated to put t200 near its real 3.9. It reproduces
baseline well below t200, but not t201 < t200. That real gap was only about 1.5 SE, so it is
possibly partly noise.

## Round 4 results (calibrated pool: 9 hunting elites + 3 normal elites, control t300)
The calibration held: t300 scored 4.14 locally vs 3.83 real, and t200 came in -0.22 vs t300
(real: +0.09). The top five of 27 variants were early loot greed +1.58, kite 80 m +1.22,
survival upgrades +1.14, retreat only below 25% +1.03 and ignore drones +0.97. The bottom
were loose aim -0.64, fall back to heal below 60% -0.50 and careful-survivor style -0.47.

## Round 5: confirmation on fresh seeds (48 matches each) - nothing held up
| change | r4 | r5 |
|---|---|---|
| early loot greed | +1.58 | -0.23 |
| kite 80 m | +1.22 | -0.21 |
| survival upgrades | +1.14 | -0.62 |
| retreat only below 25% | +1.03 | -0.88 |
| ignore drones | +0.97 | -0.62 |
| stacks k1/k2/k3/k4 | | -1.06 / -1.52 / +0.17 / -0.44 |

**Conclusion.** These were selection noise (winner's curse: the best of 27 noisy variants
shows about +1.3 by chance). Within t3core's parameter space, t300 and t200 are at a plateau.
Parameter tweaks will not move the real score; it needs new capability (better aim, dodging,
and fighting back against hunters), not different thresholds.

**Lesson for future rounds.** Always confirm the top variants on fresh seeds before merging;
a single round's top-5 means nothing with ±0.65 SE.

## Rounds 6 + 7: new combat abilities (calibrated pool, control t300, ~77 matches each per round)
New t3core options: `smart_aim` (lead with acceleration, aim at the visible body part),
`evasive` (random strafing when a visible mech aims at us), `arm_first` (no fights before a
second weapon, first 75 s), `laser_precharge`.

| variant | r6 | r7 | combined |
|---|---|---|---|
| smart_aim | +0.64 | +0.31 | about +0.47 +- 0.32 (positive both times, not significant) |
| smart_aim + evasive 0.8 | +0.91 | -0.49 | about +0.2 |
| all four | -0.17 | -0.24 | about -0.2 |
| evasive 1.0 | -0.13 | -0.69 | about -0.4 |
| laser_precharge | +0.18 | -1.03 | about -0.4 |
| arm_first | +0.10 | -1.04 | about -0.5 |
| evasive 0.5 | -0.29 | -1.62 | about -1.0 |

**Conclusion.** Only smart aiming is consistently positive, and only by about +0.5. That is too
small for 48 real matches to detect (+-0.65). Random strafing, pre-charging and arming first
hurt or do nothing.

## Rounds 8 + 9: rooftop design (t400 as control, calibrated pool)
Real result first: t400 (t300 + smart aim) scored 3.81, so the t200/t300/t400 family sits at
about 3.8-3.9 whatever we tune.

New t3core option `roof_mode`: pick a flat roof inside the next circle, jet-climb onto it, and
hold still near its middle. Re-pick when the zone moves. In smoke tests the roof bots spent
74-91% of their alive time on roofs, so the mechanics work.

| variant | r8 | r9 |
|---|---|---|
| loot 60 s, then climb | -0.18 | -0.46 |
| roofs 5-25 m | -0.90 | -0.53 |
| only shoot back from the roof | -0.65 | -0.72 |
| roofs 8-40 m | -1.36 | -1.12 |
| roofs 12-45 m | -1.25 | -1.21 |

**Conclusion.** Clearly worse, and worse the more time spent on roofs and the higher the roof.
Roof bots died earlier (median survival 50-75 s vs about 90 s for t400), looted less, and took
a few zone deaths when leaving a roof late. Hiding, in any form, keeps losing; this is the third
time (t201, careful-survivor variants, roofs).

# The plateau and the weapons race (2026-11-22)
Real: t500 (aggressive elite style) scored 3.73. Four very different bots now sit at 3.73-3.92,
while the leaders reach 7+. A plateau that ignores strategy points to something all t3core bots
share.

Checked and ruled out:
- **Speed:** t500 on 0.2 / 0.1 of a CPU still answered 99% / 98% of observations in time.
- **Hidden crashes:** 6 full-length local matches with stderr logs produced no tracebacks.

Evidence from the kit's recording (the only real-match data we have, t = 0-37 s):
- 3 of 16 mechs were dead by 27 s; the recorded mech died at 37 s.
- Its killer (mech 10) had a **laser + gun**: 4 full-charge laser hits (1,260 damage) plus
  405 gun damage, from 55-153 m. The recorded mech dealt only 472 back.
- The recorded mech never took a weapon, although lasers and lightning were in view for 200+
  observations.

The same weakness shows in our bots: in the calibrated sim, t400 dies holding only the gun 44-50%
of the time, and has a laser just 17-22% of the time. The cause is the shared loot logic: weapons
come after drops and cubes, only within 80 m, and the bot forgets pickups that leave its view.

New t3core option `weapon_rush`:
- remembers every pickup it has seen
- spins 360 degrees at the start to spot loot
- goes for laser, then lightning, before cubes
- drops the gun or a mortar to hold laser + lightning

Smoke test: 9 of 16 games ended with laser + lightning (t400: gun only in 8 of 16).

## Rounds 10 + 11: weapons race vs t400 (calibrated pool)
| variant | r10 | r11 |
|---|---|---|
| keep the gun | +0.65 | -0.61 |
| no opening spin | +0.11 | -0.71 |
| t200 + rush | +0.21 | -0.86 |
| full rush (laser + lightning, drop gun) | +0.03 | -0.88 |
| rush within 120 m only | +0.18 | -1.04 |

**Conclusion.** No gain in the sim. More importantly, after 11 rounds nothing has moved the
calibrated sim by more than noise, even physically large changes (loadout, rooftops,
aggression). In the sim, the 9 hunting opponents decide the outcome almost regardless of what
our bot does. So this sim can reproduce the real score level, but it cannot rank designs. It
has the same blind spot as the real plateau, which suggests the hunting pool is not how the
real built-ins behave.
