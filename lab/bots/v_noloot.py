import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import t3core
t3core.main({'cube_range': 0.0, 'weapon_range': 30.0, 'crates': False}, name='v_noloot')
