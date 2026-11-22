"""t711: t700 + pick fights by matchup and HP.

Uses mechs[].weapons and mechs[].hp to decide which fights to start (anyone shooting us is still
fought back):
- skip a target whose matchup is worse than ours: it holds lightning and we don't (within 70 m),
  it holds a laser and we don't (beyond 50 m), or it is 25%+ healthier than us
- prefer good matchups: our laser vs its mortar (cook-off +60%), our lightning vs its laser (short)
"""
import t3core

t3core.main({
    "drift_frac": 0.95, "npc_farm": True, "upgrades": "damage", "smart_aim": True, "weapon_rush": True,
    "matchup": True, "laser_hold": True, "laser_hold_max": 0.6, "calm_hp": 0.85, "laser_engage": 180.0, "fight_pick": True,
}, name="t711")
