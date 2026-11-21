import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import t3core
t3core.main({'engage_range': 60.0, 'cover': True, 'cover_hp': 0.9, 'drift_frac': 0.2, 'crates': False}, name='camper')
