"""t300: t200 + three changes that each held up across tournament rounds r1-r3 (lab/NOTES.md).

- drift_frac 0.95: once inside the safe disc, hold position near where we entered it instead of
  walking toward the next-circle centre (fewer encounters with mechs converging on the middle).
- npc_farm: when healthy and no mechs are around, hunt NPC drones for their 2 cubes each.
- upgrades "damage": damage-first upgrade picks (works with the extra cubes from farming).
"""
import t3core

t3core.main({"drift_frac": 0.95, "npc_farm": True, "upgrades": "damage"}, name="t300")
