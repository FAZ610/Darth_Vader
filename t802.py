"""t802: earlier end-zone ghosting variant."""
import t8core

t8core.main(t8core.Profile(
    name="t802-early-ghost",
    base={"SmartAim": True, "EndGhost": 240},
    squad={"DropRun": 220, "FightLoot": 70},
    ffa={"Bubble": 180, "BubbleFight": 50, "UseDrops": True, "EndHide": 60},
    ghost={"Practice": False, "Ghost": True, "EndHide": 70, "LoseRule": False, "FightLoot": 0},
    salt=802,
))
