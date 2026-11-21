import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import t3core
t3core.main({'drift_frac': 0.95, 'npc_farm': True, 'upgrades': 'damage', 'pref_lightning': 4}, name='w_lightning')
