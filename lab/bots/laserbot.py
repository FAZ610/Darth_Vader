import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import t3core
t3core.main({'weapon_rush': True, 'drop_gun': False, 'smart_aim': True, 'engage_range': 200.0, 'weak_engage': 220.0, 'kite_dist': 120.0, 'combat_range': 230.0, 'cover_hp': 0.35, 'cover_range': 1000000000.0, 'npc_farm': True, 'upgrades': 'damage', 'loot_enemy_r': 0.0, 'drift_frac': 0.6}, name='laserbot')
