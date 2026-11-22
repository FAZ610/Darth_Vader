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

# ---- tougher opponent: loots and farms early, upgrades damage, picks off weakened mechs,
# keeps laser range, takes cover only when low. Used with perks to stand in for built-ins.
VARIANTS["elite"] = ({"engage_range": 180.0, "weak_engage": 200.0, "cover_hp": 0.35, "cover_range": 1e9,
                      "target_mode": "weak", "kite_dist": 60.0, "npc_farm": True, "early_greedy": True,
                      "upgrades": "damage", "seek_gunfire": True, "strafe_w": 1.2, "loot_enemy_r": 0.0,
                      "combat_range": 200.0, "drop_crowd_r": 15.0}, "strong opponent")

# ---- round 4: variants of t300 (real 3.83 ~ t200 3.92)
T300 = {"drift_frac": 0.95, "npc_farm": True, "upgrades": "damage"}


def _t3(extra, why):
    p = dict(T300)
    p.update(extra)
    return p, why


VARIANTS.update({
    "t300": _t3({}, "t300 itself (control)"),
    # ablations: which part of t300 matters
    "a_no_edge": _t3({"drift_frac": 0.6}, "t300 without edge holding"),
    "a_no_farm": _t3({"npc_farm": False}, "t300 without NPC farming"),
    "a_surv_upg": _t3({"upgrades": "survival"}, "t300 with survival upgrades"),
    # minor tweaks
    "w_kite80": _t3({"kite_dist": 80.0}, "+ keep 80-115 m in fights"),
    "w_kite60": _t3({"kite_dist": 60.0}, "+ keep 60-95 m in fights"),
    "w_engage120": _t3({"engage_range": 120.0}, "+ shoot out to 120 m"),
    "w_engage70": _t3({"engage_range": 70.0}, "+ shoot only within 70 m"),
    "w_cover_early": _t3({"cover_hp": 0.75}, "+ seek cover below 75% HP"),
    "w_cover_late": _t3({"cover_hp": 0.45}, "+ seek cover only below 45% HP"),
    "w_margin_big": _t3({"margin_frac": 0.35, "margin_cap": 40.0}, "+ deeper inside next circle"),
    "w_target_weak": _t3({"target_mode": "weak"}, "+ focus lowest HP"),
    "w_lightning": _t3({"pref_lightning": 4}, "+ prefer lightning"),
    "w_strafe_hard": _t3({"strafe_w": 1.4}, "+ strafe harder"),
    "w_aim_loose": _t3({"aim_tol": 2.5}, "+ looser trigger"),
    "w_no_drops": _t3({"drops": False}, "+ ignore supply drops"),
    "w_drop_contest": _t3({"drop_crowd_r": 12.0, "drop_range": 250.0}, "+ contest supply drops"),
    "w_greedy_early": _t3({"early_greedy": True}, "+ loot range x1.8 for 100 s"),
    "w_npc_ignore": _t3({"npc_avoid": 0.0}, "+ no drone avoidance"),
    "w_retreat_late": _t3({"retreat_hp": 0.25}, "+ only back off below 25% HP"),
    # new behaviours
    "w_heal60": _t3({"heal_retreat": 0.6}, "+ fall back across the safe disc below 60% HP after being shot"),
    "w_heal40": _t3({"heal_retreat": 0.4}, "+ fall back below 40% HP"),
    "w_avoid_fire": _t3({"avoid_gunfire": True}, "+ move away from heard gunfire"),
    "w_third": _t3({"seek_gunfire": True, "target_mode": "weak"}, "+ third-party heard fights"),
    # bigger combinations
    "m_fighter": _t3({"kite_dist": 70.0, "engage_range": 120.0, "target_mode": "weak", "strafe_w": 1.2},
                     "t300 as a disciplined fighter"),
    "m_survivor": _t3({"heal_retreat": 0.6, "cover_hp": 0.75, "avoid_gunfire": True, "margin_frac": 0.35,
                       "margin_cap": 40.0}, "t300 as a careful survivor"),
    "m_grower": _t3({"early_greedy": True, "drop_crowd_r": 12.0, "drop_range": 250.0, "kite_dist": 80.0},
                    "t300 that grows faster (loot, drops) then kites"),
})


# ---- round 5: stack the round-4 winners on t300, one at a time
VARIANTS.update({
    "k1_greedy_kite": _t3({"early_greedy": True, "kite_dist": 80.0}, "t300 + early greed + kite 80"),
    "k2_plus_surv": _t3({"early_greedy": True, "kite_dist": 80.0, "upgrades": "survival"}, "k1 + survival upgrades"),
    "k3_plus_late": _t3({"early_greedy": True, "kite_dist": 80.0, "upgrades": "survival", "retreat_hp": 0.25},
                        "k2 + back off only below 25%"),
    "k4_all": _t3({"early_greedy": True, "kite_dist": 80.0, "upgrades": "survival", "retreat_hp": 0.25,
                   "npc_avoid": 0.0, "drop_crowd_r": 12.0, "drop_range": 250.0}, "every round-4 winner"),
})


# ---- round 6: combat abilities on top of t300
VARIANTS.update({
    "x_aim": _t3({"smart_aim": True}, "t300 + acceleration lead and visible-part aiming"),
    "x_evade05": _t3({"evasive": 0.5}, "t300 + light random strafing when aimed at"),
    "x_evade10": _t3({"evasive": 1.0}, "t300 + strong random strafing when aimed at"),
    "x_arm": _t3({"arm_first": True}, "t300 + get a second weapon before fighting (first 75 s)"),
    "x_precharge": _t3({"laser_precharge": True}, "t300 + pre-charge the laser when mechs are in range"),
    "x_aim_evade": _t3({"smart_aim": True, "evasive": 0.8}, "t300 + smart aim + evasion"),
    "x_all": _t3({"smart_aim": True, "evasive": 0.8, "arm_first": True, "laser_precharge": True},
                 "t300 + all four combat abilities"),
})


# ---- round 8: rooftop design on top of t400 (t300 + smart aim)
T400 = dict(T300, smart_aim=True)


def _t4(extra, why):
    p = dict(T400)
    p.update(extra)
    return p, why


VARIANTS.update({
    "t400": _t4({}, "t400 itself"),
    "r_roof": _t4({"roof_mode": True}, "rooftop holder, roofs 8-40 m"),
    "r_roof_low": _t4({"roof_mode": True, "roof_min_h": 5.0, "roof_max_h": 25.0}, "lower roofs 5-25 m (cheaper climbs)"),
    "r_roof_high": _t4({"roof_mode": True, "roof_min_h": 12.0, "roof_max_h": 45.0}, "higher roofs 12-45 m"),
    "r_roof_quiet": _t4({"roof_mode": True, "roof_engage": False}, "rooftop, only shoot back at attackers"),
    "r_roof_loot": _t4({"roof_mode": True, "roof_after": 60.0}, "loot for the first 60 s, then climb"),
})


# ---- round 10: weapons race (real recording: the killer had a laser within seconds; half our
# deaths happen holding only the gun)
VARIANTS.update({
    "q_rush": _t4({"weapon_rush": True}, "t400 + weapons race (laser+lightning, drop gun)"),
    "q_rush_keepgun": _t4({"weapon_rush": True, "drop_gun": False}, "weapons race, keep the gun"),
    "q_rush_nospin": _t4({"weapon_rush": True, "opening_spin": False}, "weapons race without the opening spin"),
    "q_rush_near": _t4({"weapon_rush": True, "rush_range": 120.0}, "weapons race within 120 m only"),
    "q_rush_t200": ({"weapon_rush": True}, "t200 + weapons race"),
})


# ---- round 12: a built-in-like opponent modelled on the recorded killer (mech 10): laser + gun by
# ~5 s, fights at 95-150 m with full-charge lasers plus gun fire, kites to hold that range.
VARIANTS["laserbot"] = ({"weapon_rush": True, "drop_gun": False, "smart_aim": True, "engage_range": 200.0,
                         "weak_engage": 220.0, "kite_dist": 120.0, "combat_range": 230.0, "cover_hp": 0.35,
                         "cover_range": 1e9, "npc_farm": True, "upgrades": "damage", "loot_enemy_r": 0.0,
                         "drift_frac": 0.6}, "built-in stand-in: laser sniper")
T600 = dict(T400, weapon_rush=True)
VARIANTS["t600"] = (dict(T600), "t600 itself")


def _t6(extra, why):
    p = dict(T600)
    p.update(extra)
    return p, why


# ---- round 12: use more of the observation, on top of t600 (real 4.52)
VARIANTS.update({
    "y_hold": _t6({"laser_hold": True}, "never waste a charged laser"),
    "y_lrange": _t6({"laser_engage": 180.0}, "with a laser, engage out to 180 m"),
    "y_matchup": _t6({"matchup": True}, "weapon triangle stance (push lightning, avoid enemy lightning)"),
    "y_ccover": _t6({"charge_cover": True}, "break LOS from a laser charging at us"),
    "y_upg": _t6({"upg_loadout": True}, "loadout-aware upgrades"),
    "y_calm": _t6({"calm_hp": 0.85}, "no crate/drone shooting below 85% HP (keep regen)"),
    "y_all": _t6({"laser_hold": True, "laser_engage": 180.0, "matchup": True, "charge_cover": True,
                  "upg_loadout": True, "calm_hp": 0.85}, "all six"),
})


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
