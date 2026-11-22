"""t712: t710 + t711 together: fights start only within 90 m and only good matchups (see t711)."""
import t3core

t3core.main({
    "drift_frac": 0.95, "npc_farm": True, "upgrades": "damage", "smart_aim": True, "weapon_rush": True,
    "matchup": True, "laser_hold": True, "laser_hold_max": 0.6, "calm_hp": 0.85, "fight_pick": True,
}, name="t712")
