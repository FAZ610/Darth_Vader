import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import t3core
t3core.main({'engage_range': 200.0, 'pref_laser': 5, 'kite_dist': 110.0, 'aim_tol': 0.8}, name='s_sniper')
