"""t500: the `elite` style as a real-world probe (lab/NOTES.md).

Deliberately different in kind from t200/t300/t400 (all ~3.8-3.9 for real): grows hard and fights.
- loots far (x1.8 range) for the first 100 s, hunts NPC drones, contests supply drops
- damage-first upgrades
- engages mechs out to 180 m, focuses the lowest-HP target, third-parties heard fights
- holds ~60-95 m in fights while strafing; takes cover only below 35% HP
Its real score tells us whether the built-ins can be beaten by snowballing.
"""
import t3core

t3core.main({
    "engage_range": 180.0, "weak_engage": 200.0, "cover_hp": 0.35, "cover_range": 1e9,
    "target_mode": "weak", "kite_dist": 60.0, "npc_farm": True, "early_greedy": True,
    "upgrades": "damage", "seek_gunfire": True, "strafe_w": 1.2, "loot_enemy_r": 0.0,
    "combat_range": 200.0, "drop_crowd_r": 15.0,
}, name="t500")
