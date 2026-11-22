"""t701: play like the built-in that won the recorded match (mech 10): a laser + gun sniper.

Big change in style. t600 drops the gun for laser + lightning and fights within 90 m; t701 copies the
recorded killer instead (laser by 5 s, 4/5 full-charge hits at 95-146 m, gun fire in between):
- weapons race for the laser, but keeps the gun (laser + gun; lightning only into an empty slot)
- engages any mech it sees out to 200 m and holds ~120-155 m from its target while fighting
- laser shot discipline (never waste a charge, hold a full charge at most 0.6 s)
- runs for cover only below 35% HP (at 120 m+ it is the one doing the sniping)
"""
import t3core

t3core.main({
    "drift_frac": 0.95, "npc_farm": True, "upgrades": "damage", "smart_aim": True, "weapon_rush": True,
    "drop_gun": False, "engage_range": 200.0, "weak_engage": 220.0, "kite_dist": 120.0, "combat_range": 230.0,
    "cover_hp": 0.35, "cover_range": 1e9, "laser_hold": True, "laser_hold_max": 0.6,
}, name="t701")
