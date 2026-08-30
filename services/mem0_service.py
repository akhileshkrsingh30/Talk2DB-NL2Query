import logging
from typing import List, Dict, Any, Optional

class Mem0Service:
    """Disabled / Stub Mem0 Service. All access is granted without external memory queries."""
    def __init__(self):
        self.client = None
        self.initialized = False

    def initialize(self):
        self.initialized = False
        self.client = None

    def is_ready(self) -> bool:
        return False

    def get_user_permissions(self, user_id: str) -> Dict[str, Any]:
        return {
            "role": "admin",
            "support_level": 5,
            "allowed_tables": ["*"],
            "restricted_tables": [],
            "restricted_columns": {},
            "row_filters": [],
        }

    def invalidate_cache(self, user_id: Optional[str] = None):
        pass

    def filter_schema_for_user(self, schema_text: str, permissions: Dict[str, Any]) -> str:
        return schema_text

    def add_audit_log(self, user_id: str, session_id: str, query: str, status: str):
        pass
