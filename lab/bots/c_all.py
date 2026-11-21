import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import t3core
t3core.main({'drift_frac': 0.95, 'kite_dist': 80.0, 'npc_farm': True, 'upgrades': 'damage', 'margin_frac': 0.1, 'margin_cap': 8.0}, name='c_all')
