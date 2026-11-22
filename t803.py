"""t803: retreat-and-cover-focused variant."""
import t8core

t8core.main(t8core.Profile(
    name="t803-cover",
    base={"SmartAim": True, "EndGhost": 140},
    squad={
        "DropRun": 180,
        "RetreatHP": 0.48,
        "RecoverHP": 0.82,
        "CrowdHide": True,
        "LoseRule": True,
        "FightLoot": 60,
    },
    ffa={"Bubble": 210, "BubbleFight": 45, "UseDrops": True, "EndHide": 80},
    ghost={"EndHide": 80, "LoseRule": False},
    salt=803,
))
