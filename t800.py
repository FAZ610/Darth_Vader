"""t800: rogue_agi's pilot (giddygiddyboy family, MIT) ported to Python, plus our additions.

Real practice scores: our t3core bots t200-t710 sit at 3.7-4.5, while rogue_agi's Go pilot scores 6.39
(board #2). t8core.py ports its strategy:
- practice vs the house squad: laser first (seek up to 240 m), laser upgrades, lethal partial laser
  release, target sticking and low-HP bonus, "lose rule" retreat to cover, fight-time cube grabs
- end game in practice (circle <= 140 m): stop fighting the squad and hide (Sandeep's rule)
- free-for-all (mechs die that we did not kill): survival bubble, hidden spots, safe weapon grabs, drops

Ours on top:
- SmartAim: lead with the target's measured acceleration (t3core smart_aim, positive in rounds 6-7)
- DropRun 220 in practice: take supply drops that no known mech is near (Jishnu's log: +0.36)
- salt 800: a new RNG draw (the scorer is deterministic; each salt is a new draw of the same strategy)
"""
import t8core

t8core.main(t8core.Profile(
    name="t800",
    base={"SmartAim": True},
    squad={"DropRun": 220},
    salt=800,
))
