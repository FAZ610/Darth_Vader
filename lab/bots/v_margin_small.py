import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import t3core
t3core.main({'margin_frac': 0.1, 'margin_cap': 8.0}, name='v_margin_small')
