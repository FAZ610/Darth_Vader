import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import t3core
t3core.main({'cover_hp': 0.35, 'cover_range': 1000000000.0}, name='v_cover_lowonly')
