"""t806: stronger fight-time cube collection based on t801."""
import t8core

t8core.main(t8core.Profile(
    name="t806-cube-hunt-plus",
    base={"SmartAim": True, "CubeGoal": 10},
    squad={
        "DropRun": 260,
        "FightLoot": 130,
        "FarmHP": 0.35,
        "CrateUntil": 240,
    },
    ffa={"Bubble": 200, "BubbleFight": 55, "UseDrops": True, "EndHide": 60},
    ghost={"EndHide": 60},
    salt=806,
))
