import os
import json
from datetime import datetime

# Add project root to path
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import gotw

if __name__ == '__main__':
    next_update, next_week = gotw.compute_next_update()
    if next_week is None:
        print(f'Next update (daily): {next_update.strftime("%Y-%m-%d %H:%M %Z")}')
    else:
        print(f'Next update (weekly) Week {next_week}: {next_update.strftime("%Y-%m-%d %H:%M %Z")}')
