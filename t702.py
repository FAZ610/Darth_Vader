"""t702: lightning brawler.

Big change in loadout priority. Lightning is by far the strongest weapon up close (60 dmg every
0.25 s = 240 DPS plus chains, vs ~100 DPS for the gun and ~130 for the laser) and it shorts the
lasers the built-ins snipe with. t702:
- races for lightning first, then a laser (drops mortar, then gun)
- weapon triangle: closes in on any non-lightning mech within 110 m when healthy (> 45% HP, > 35 energy),
  and keeps out of 45 m of mechs that also hold lightning
- laser shot discipline as in t700; regen-friendly (no crate/drone shooting below 85% HP)
"""
import t3core

t3core.main({
    "drift_frac": 0.95, "npc_farm": True, "upgrades": "damage", "smart_aim": True, "weapon_rush": True,
    "rush_first": "lightning", "matchup": True, "push_range": 110.0, "laser_hold": True,
    "laser_hold_max": 0.6, "calm_hp": 0.85,
}, name="t702")
