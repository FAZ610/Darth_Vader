import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import t3core
t3core.main({'seek_gunfire': True, 'target_mode': 'weak', 'engage_range': 120.0, 'early_greedy': True}, name='s_third')
