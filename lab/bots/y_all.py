import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import t3core
t3core.main({'drift_frac': 0.95, 'npc_farm': True, 'upgrades': 'damage', 'smart_aim': True, 'weapon_rush': True, 'laser_hold': True, 'laser_engage': 180.0, 'matchup': True, 'charge_cover': True, 'upg_loadout': True, 'calm_hp': 0.85}, name='y_all')
