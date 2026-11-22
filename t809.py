"""t809: more persistent cube farming based on t801."""
import t8core

t8core.main(t8core.Profile(
    name="t809-persistent-farm",
    base={"SmartAim": True, "CubeGoal": 10},
    squad={
        "DropRun": 260,
        "FightLoot": 100,
        "FarmHP": 0.25,
        "CrateUntil": 180,
    },
    ffa={"Bubble": 200, "BubbleFight": 55, "UseDrops": True, "EndHide": 60},
    ghost={"EndHide": 60},
    salt=809,
))
