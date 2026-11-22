"""t801: cube-hunting variant."""
import t8core

t8core.main(t8core.Profile(
    name="t801-cube-hunter",
    base={"SmartAim": True, "CubeGoal": 10},
    squad={"DropRun": 260, "FightLoot": 100, "FarmHP": 0.35, "CrateUntil": 180},
    ffa={"Bubble": 200, "BubbleFight": 55, "UseDrops": True, "EndHide": 60},
    ghost={"EndHide": 60},
    salt=801,
))
