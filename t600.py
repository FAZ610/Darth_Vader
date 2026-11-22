"""t600: t400 + weapons race, a real-world probe (lab/NOTES.md, rounds 10-11).

Real-match evidence: the recorded killer held a laser by 8 s and won with full-charge hits at 55-153 m,
while our bots usually die holding only the gun. The simulator cannot judge loadouts, so the real score decides.
- opening 360 deg spin to spot pickups, remembers every pickup it has seen
- rushes the nearest laser (then lightning) within 220 m before cubes and drops
- swaps out the mortar, then the gun, for laser/lightning
"""
import t3core

t3core.main({
    "drift_frac": 0.95, "npc_farm": True, "upgrades": "damage", "smart_aim": True,
    "weapon_rush": True,
}, name="t600")
