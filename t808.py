"""t808: t801 cube snowballing combined with laser finishing."""
import t8core

t8core.main(t8core.Profile(
    name="t808-cube-finisher",
    base={"SmartAim": True, "CubeGoal": 10},
    squad={
        "DropRun": 260,
        "FightLoot": 100,
        "FarmHP": 0.35,
        "CrateUntil": 180,
        "Stick": 260,
        "LowBonus": 260,
        "Finish": 32,
        "FinishHP": 0.42,
        "FinishRush": True,
        "Backstab": 70,
    },
    ffa={"Bubble": 200, "BubbleFight": 55, "UseDrops": True, "EndHide": 60},
    ghost={"EndHide": 60},
    salt=808,
))
