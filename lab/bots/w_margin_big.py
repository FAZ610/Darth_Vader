import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import t3core
t3core.main({'drift_frac': 0.95, 'npc_farm': True, 'upgrades': 'damage', 'margin_frac': 0.35, 'margin_cap': 40.0}, name='w_margin_big')
