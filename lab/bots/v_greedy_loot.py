import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import t3core
t3core.main({'cube_range': 140.0, 'weapon_range': 140.0, 'crate_range': 110.0, 'detour_slack': 12.0}, name='v_greedy_loot')
