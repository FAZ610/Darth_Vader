import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import t3core
t3core.main({'drift_frac': 0.95, 'npc_farm': True, 'upgrades': 'damage', 'kite_dist': 70.0, 'engage_range': 120.0, 'target_mode': 'weak', 'strafe_w': 1.2}, name='m_fighter')
