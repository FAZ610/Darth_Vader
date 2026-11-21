import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import t3core
t3core.main({'drift_frac': 0.95, 'npc_farm': True, 'upgrades': 'damage', 'early_greedy': True, 'drop_crowd_r': 12.0, 'drop_range': 250.0, 'kite_dist': 80.0}, name='m_grower')
