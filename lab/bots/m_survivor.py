import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import t3core
t3core.main({'drift_frac': 0.95, 'npc_farm': True, 'upgrades': 'damage', 'heal_retreat': 0.6, 'cover_hp': 0.75, 'avoid_gunfire': True, 'margin_frac': 0.35, 'margin_cap': 40.0}, name='m_survivor')
