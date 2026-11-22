"""t807: wider supply-drop search based on t801."""
import t8core

t8core.main(t8core.Profile(
    name="t807-wide-drop",
    base={"SmartAim": True, "CubeGoal": 10},
    squad={
        "DropRun": 300,
        "FightLoot": 100,
        "FarmHP": 0.35,
        "CrateUntil": 180,
    },
    ffa={"Bubble": 200, "BubbleFight": 55, "UseDrops": True, "EndHide": 60},
    ghost={"EndHide": 60},
    salt=807,
))
