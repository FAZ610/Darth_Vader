import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import t3core
t3core.main({'drop_crowd_r': 10.0, 'drop_range': 250.0}, name='v_drop_contest')
