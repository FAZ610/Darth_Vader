"""t805: cautious free-for-all and survival variant."""
import t8core

t8core.main(t8core.Profile(
    name="t805-survival",
    base={"SmartAim": True, "EndGhost": 140},
    squad={"DropRun": 220, "FightLoot": 45, "RetreatHP": 0.42},
    ffa={
        "Bubble": 220,
        "BubbleFight": 65,
        "UseDrops": True,
        "EndHide": 90,
        "HomeExpo": 180,
        "LootRadius": 100,
        "DropRun": 180,
    },
    ghost={"EndHide": 90, "Ghost": True, "LoseRule": False},
    salt=805,
))
