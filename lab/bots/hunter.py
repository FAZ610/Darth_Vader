import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import t3core
t3core.main({'engage_range': 200.0, 'weak_engage': 200.0, 'cover': False, 'chase': True, 'silent': False, 'loot_enemy_r': 0.0, 'npc_farm': True, 'upgrades': 'damage', 'combat_range': 200.0}, name='hunter')
