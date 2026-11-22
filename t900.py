"""t900: combined cube economy, cover, laser, and FFA survival strategy."""
import t8core

t8core.main(t8core.Profile(
    name="t900",
    base={
        "SmartAim": True,
        "CubeGoal": 10,
        "EndGhost": 140,
    },
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
        "LoseRule": True,
        "RetreatHP": 0.38,
        "RecoverHP": 0.80,
    },
    ffa={
        "Bubble": 200,
        "BubbleFight": 55,
        "UseDrops": True,
        "EndHide": 60,
        "HomeExpo": 150,
        "LootRadius": 100,
        "DropRun": 220,
    },
    ghost={
        "EndHide": 60,
        "Ghost": True,
        "LoseRule": False,
        "FightLoot": 0,
        "Peek": False,
    },
    salt=900,
))
