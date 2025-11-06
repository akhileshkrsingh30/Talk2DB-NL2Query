import urllib.parse
from typing import Dict, Any

def make_db_cache_key(creds: Dict[str, Any]) -> str:
    """Create a cache key for database schema"""
    # Do NOT include password; schema does not depend on it
    return f"{creds.get('host')}:{creds.get('port')}/{creds.get('database')}@{creds.get('user')}"