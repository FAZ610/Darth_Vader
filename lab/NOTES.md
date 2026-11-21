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
