"""t710: t700 without the 180 m laser engagement.

t700 (better for real) bundled four combat changes; t701, which fights at long range, scored worse
for real. t710 tests whether starting laser fights at 90-180 m is t700's weak part: it keeps the
weapon-triangle stance, laser shot discipline and regen-friendly looting, and starts fights only
within 90 m (or when shot at), like t600.
"""
import t3core

t3core.main({
    "drift_frac": 0.95, "npc_farm": True, "upgrades": "damage", "smart_aim": True, "weapon_rush": True,
    "matchup": True, "laser_hold": True, "laser_hold_max": 0.6, "calm_hp": 0.85,
}, name="t710")
