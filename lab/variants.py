"""Variant table for t3core experiments. `python lab/variants.py` (re)writes lab/bots/<name>.py.

Each entry: name -> (params overriding t3core.DEFAULTS, one-line hypothesis).
Defaults reproduce t200 (real score 3.92).
"""
import os

VARIANTS = {
    # ---- opponents (not candidates)
    "hunter": ({"engage_range": 200.0, "weak_engage": 200.0, "cover": False, "chase": True, "silent": False,
                "loot_enemy_r": 0.0, "npc_farm": True, "upgrades": "damage", "combat_range": 200.0},
               "aggressive stand-in for strong built-ins: chases and shoots anything it sees"),
    "camper": ({"engage_range": 60.0, "cover": True, "cover_hp": 0.9, "drift_frac": 0.2, "crates": False},
               "passive centre camper"),
    # ---- round 1: one change each vs t200
    "v_engage150": ({"engage_range": 150.0}, "shoot visible mechs out to 150 m (t200: 90)"),
    "v_engage50": ({"engage_range": 50.0}, "shoot only mechs within 50 m"),
    "v_nocover": ({"cover": False}, "never run for cover; stand and trade"),
    "v_cover_lowonly": ({"cover_hp": 0.35, "cover_range": 1e9}, "cover only when below 35% HP"),
    "v_chase": ({"chase": True, "combat_range": 180.0}, "push toward targets beyond 45 m"),
    "v_nosilent": ({"silent": False}, "always walk at full speed"),
    "v_margin_big": ({"margin_frac": 0.4, "margin_cap": 45.0}, "stay deeper inside the next circle"),
    "v_margin_small": ({"margin_frac": 0.1, "margin_cap": 8.0}, "sit near the edge of the next circle"),
    "v_center": ({"drift_frac": 0.2}, "drift close to the next-circle centre"),
    "v_edge": ({"drift_frac": 0.95}, "hold near where we enter the safe disc"),
    "v_late_center": ({"late_center": True}, "go to the centre once the next radius is <= 140 m"),
    "v_greedy_loot": ({"cube_range": 140.0, "weapon_range": 140.0, "crate_range": 110.0, "detour_slack": 12.0},
                      "chase loot further"),
    "v_noloot": ({"cube_range": 0.0, "weapon_range": 30.0, "crates": False}, "ignore loot except underfoot"),
    "v_nodrops": ({"drops": False}, "ignore supply drops"),
    "v_npc_farm": ({"npc_farm": True}, "hunt NPC drones for cubes when healthy"),
    "v_dmg_upg": ({"upgrades": "damage"}, "damage-first upgrades"),
    "v_mob_upg": ({"upgrades": "mobility"}, "mobility-first upgrades"),
    "v_pref_lightning": ({"pref_lightning": 4}, "prefer lightning over laser"),
    "v_pref_mortar": ({"pref_mortar": 4}, "prefer mortar"),
    "v_nostrafe": ({"strafe": False}, "no strafing in fights"),
    "v_strafe_hard": ({"strafe_w": 1.6}, "strafe harder"),
    "v_aim_loose": ({"aim_tol": 3.0}, "fire with looser aim"),
    "v_aim_tight": ({"aim_tol": 0.8}, "fire only when well aimed"),
    "v_jump": ({"jump_evade": True}, "jump periodically when under fire"),
    "v_avoid_gunfire": ({"avoid_gunfire": True}, "move away from heard gunfire"),
    "v_retreat_early": ({"retreat_hp": 0.6}, "back off in fights below 60% HP"),
    "v_npc_ignore": ({"npc_avoid": 0.0}, "don't detour around drones"),
    "v_urgent_early": ({"urgent_slack": 20.0}, "treat the zone as urgent sooner"),
    # ---- round 1: structural changes and whole play-styles
    "v_early_greedy": ({"early_greedy": True}, "loot range x1.8 for the first 100 s"),
    "v_target_weak": ({"target_mode": "weak"}, "focus the lowest-HP target, not the nearest"),
    "v_drop_contest": ({"drop_crowd_r": 10.0, "drop_range": 250.0}, "go for supply drops even when others are near"),
    "v_third_party": ({"seek_gunfire": True}, "drift toward heard fights when healthy"),
    "v_kite80": ({"kite_dist": 80.0}, "hold ~80-115 m from the target while fighting"),
    "v_kite40": ({"kite_dist": 40.0}, "hold ~40-75 m from the target while fighting"),
    "s_brawler": ({"engage_range": 150.0, "cover": False, "chase": True, "upgrades": "damage", "target_mode": "weak"},
                  "style: aggressive brawler"),
    "s_sniper": ({"engage_range": 200.0, "pref_laser": 5, "kite_dist": 110.0, "aim_tol": 0.8},
                 "style: long-range laser kiter"),
    "s_third": ({"seek_gunfire": True, "target_mode": "weak", "engage_range": 120.0, "early_greedy": True},
                "style: third-party opportunist"),
    # ---- round 2: combinations of round-1 winners (excluding t201's hide-from-watchers idea,
    # which won locally but lost for real)
    "c_edge_kite": ({"drift_frac": 0.95, "kite_dist": 80.0}, "edge hold + kite 80"),
    "c_edge_farm_dmg": ({"drift_frac": 0.95, "npc_farm": True, "upgrades": "damage"}, "edge + NPC farming + damage upgrades"),
    "c_all": ({"drift_frac": 0.95, "kite_dist": 80.0, "npc_farm": True, "upgrades": "damage",
               "margin_frac": 0.1, "margin_cap": 8.0}, "all round-1 winners together"),
    # ---- round 3: only the changes that held up across r1 + r2
    "c_edge_farm": ({"drift_frac": 0.95, "npc_farm": True}, "edge + NPC farming"),
    "c_edge_farm_kite": ({"drift_frac": 0.95, "npc_farm": True, "kite_dist": 80.0}, "edge + NPC farming + kite 80"),
}


def write_all(out_dir=None):
    out_dir = out_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "bots")
    os.makedirs(out_dir, exist_ok=True)
    for name, (params, _) in VARIANTS.items():
        with open(os.path.join(out_dir, name + ".py"), "w", encoding="utf-8") as fh:
            fh.write(
                "import os, sys\n"
                "sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))\n"
                "import t3core\n"
                "t3core.main(%r, name=%r)\n" % (params, name[:32]))
    return out_dir


if __name__ == "__main__":
    print("wrote", len(VARIANTS), "bots to", write_all())
