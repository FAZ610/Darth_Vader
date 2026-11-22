"""t700: t600 + combat that reads the whole observation (lab/NOTES.md, round 12-13).

Big change in how fights are run, not in where the bot goes:
- weapon triangle from mechs[].weapons: with lightning (240 DPS inside 45 m, shorts lasers) it closes
  in on targets within 85 m that have no lightning; it backs out of enemy lightning range otherwise
- laser shot discipline: a started charge is never thrown away off target, but a full charge is
  held at most 0.6 s (charging halves our speed)
- with a laser, engages out to 180 m (first strike against the laser snipers seen in the recording)
- no crate/drone shooting below 85% HP, so out-of-combat regen (45 HP/s) is not reset
Keeps t600's damage-first upgrades (loadout/armor upgrades lost in both sim pools).
"""
import t3core

t3core.main({
    "drift_frac": 0.95, "npc_farm": True, "upgrades": "damage", "smart_aim": True, "weapon_rush": True,
    "matchup": True, "laser_hold": True, "laser_hold_max": 0.6, "laser_engage": 180.0, "calm_hp": 0.85,
}, name="t700")
