"""t400: t300 + smart aiming (lab/NOTES.md, rounds 6-7).

Smart aiming leads targets using their acceleration (from velocity history), not only their
velocity, and when a target's centre is hidden it aims at the visible upper or lower body.
It was the only combat change positive in two independent calibrated rounds (+0.64, +0.31 vs t300).
"""
import t3core

t3core.main({"drift_frac": 0.95, "npc_farm": True, "upgrades": "damage", "smart_aim": True}, name="t400")
