import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import t3core
t3core.main({'engage_range': 180.0, 'weak_engage': 200.0, 'cover_hp': 0.35, 'cover_range': 1000000000.0, 'target_mode': 'weak', 'kite_dist': 60.0, 'npc_farm': True, 'early_greedy': True, 'upgrades': 'damage', 'seek_gunfire': True, 'strafe_w': 1.2, 'loot_enemy_r': 0.0, 'combat_range': 200.0, 'drop_crowd_r': 15.0}, name='elite')
