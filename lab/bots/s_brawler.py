import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import t3core
t3core.main({'engage_range': 150.0, 'cover': False, 'chase': True, 'upgrades': 'damage', 'target_mode': 'weak'}, name='s_brawler')
