"""Compatibility shim for older imports from `wotd`.

This module re-exports the new `gotw` module's public names so older code importing
`wotd` keeps working while the codebase has been migrated to Grammar of the Week (GOTW).
"""

import gotw as _gotw

# Re-export common names under the old API for backward compatibility
set_wotd = _gotw.set_gotw
find_wotd = _gotw.find_gotw
wotd_main_loop = _gotw.gotw_main_loop
DB_PATH = _gotw.DB_PATH

__all__ = [
    'set_wotd', 'find_wotd', 'wotd_main_loop', 'DB_PATH'
]