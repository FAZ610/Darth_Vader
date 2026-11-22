"""t804: laser finisher and target-sticking variant."""
import t8core

t8core.main(t8core.Profile(
    name="t804-laser-finisher",
    base={"SmartAim": True, "EndGhost": 140},
    squad={
        "DropRun": 220,
        "LaserSeek": 280,
        "LaserRange": 140,
        "MaxTarget": 280,
        "Stick": 260,
        "LowBonus": 260,
        "Finish": 32,
        "FinishHP": 0.42,
        "FinishRush": True,
        "FightLoot": 70,
        "Backstab": 70,
    },
    ffa={"Bubble": 170, "BubbleFight": 60, "UseDrops": True, "EndHide": 55},
    ghost={"EndHide": 55},
    salt=804,
))
