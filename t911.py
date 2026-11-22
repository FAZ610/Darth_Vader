"""t911: t900 with a moderate 45 m fight cube range."""
import t8core

t8core.main(t8core.Profile(
    name="t911-moderate-cube",
    base={"SmartAim": True, "CubeGoal": 10, "EndGhost": 140},
    squad={
        "DropRun": 260,
        "FightLoot": 45,
        "FarmHP": 0.35,
        "CrateUntil": 150,
        "Stick": 260,
        "LowBonus": 260,
        "Finish": 32,
        "FinishHP": 0.42,
        "FinishRush": True,
        "Backstab": 70,
        "LoseRule": True,
        "RetreatHP": 0.38,
        "RecoverHP": 0.80,
        "LaserUp": True,
    },
    ffa={
        "Bubble": 200,
        "BubbleFight": 55,
        "UseDrops": True,
        "EndHide": 60,
        "HomeExpo": 150,
        "LootRadius": 100,
        "DropRun": 220,
        "LaserUp": True,
    },
    ghost={"EndHide": 60, "Ghost": True, "LoseRule": False, "FightLoot": 0, "Peek": False, "LaserUp": True},
    salt=911,
))
