import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import t3core
t3core.main({'drift_frac': 0.95, 'npc_farm': True, 'upgrades': 'survival', 'early_greedy': True, 'kite_dist': 80.0, 'retreat_hp': 0.25, 'npc_avoid': 0.0, 'drop_crowd_r': 12.0, 'drop_range': 250.0}, name='k4_all')
