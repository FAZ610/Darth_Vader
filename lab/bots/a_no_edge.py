import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import t3core
t3core.main({'drift_frac': 0.6, 'npc_farm': True, 'upgrades': 'damage'}, name='a_no_edge')
