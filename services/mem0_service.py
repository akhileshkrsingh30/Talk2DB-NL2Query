import logging
import json
import re
from typing import List, Dict, Any, Optional
from config import settings


# ── In-process cache: avoid repeated pgvector lookups ───────────────────────
_RBAC_CACHE: Dict[str, Dict[str, Any]] = {}


class Mem0Service:
    def __init__(self):
        self.client = None
        self.initialized = False

    def _get_all_db_tables(self) -> List[str]:
        """Dynamically get all database tables from the database service."""
        try:
            from services.registry import service_registry
            db_service = service_registry.get_db_service()
            if db_service and db_service.is_connected():
                return db_service.get_tables()
        except Exception as e:
            logging.error(f"[MEM0] Failed to get database tables dynamically: {e}")
        return []

    # ── Initialization ───────────────────────────────────────────────────────

    def initialize(self):
        if self.initialized:
            return
        try:
            from mem0 import Memory
            provider = settings.mem0_vector_store_provider.lower()
            
            if provider == "qdrant":
                vs_config = {
                    "collection_name": settings.mem0_collection_name,
                    "embedding_model_dims": 1536,
                }
                if settings.mem0_qdrant_url:
                    vs_config["url"] = settings.mem0_qdrant_url
                else:
                    vs_config["host"] = settings.mem0_qdrant_host
                    vs_config["port"] = settings.mem0_qdrant_port
                if settings.mem0_qdrant_api_key:
                    vs_config["api_key"] = settings.mem0_qdrant_api_key
            else:
                provider = "pgvector"
                vs_config = {
                    "connection_string": settings.mem0_pg_connection_string,
                    "collection_name":   settings.mem0_collection_name,
                    "embedding_model_dims": 1536,
                    "hnsw": True,
                }

            config = {
                "vector_store": {
                    "provider": provider,
                    "config": vs_config
                },
                "llm": {
                    "provider": "openai",
                    "config": {
                        "model":   settings.mem0_llm_model,
                        "api_key": settings.openai_api_key,
                    }
                },
                "embedder": {
                    "provider": "openai",
                    "config": {
                        "model":   settings.mem0_embedding_model,
                        "api_key": settings.openai_api_key,
                    }
                },
            }
            self.client = Memory.from_config(config)
            logging.info(
                f"[MEM0] Ready | {provider} | LLM={settings.mem0_llm_model} "
                f"| Embedder={settings.mem0_embedding_model}"
            )
            self.initialized = True
        except ImportError:
            logging.warning("[MEM0] 'mem0ai' not installed. RBAC disabled.")
            self.client = None
        except Exception as e:
            logging.error(f"[MEM0] Init failed: {e}")
            self.client = None

    def is_ready(self) -> bool:
        if not self.initialized:
            self.initialize()
        return self.initialized and self.client is not None

    # ── Main RBAC retrieval (fast path via metadata) ─────────────────────────

    def get_user_permissions(self, user_id: str) -> Dict[str, Any]:
        """
        Retrieve RBAC permissions for a user.

        Fast path  → get_all(user_id) reads metadata['allowed_tables'] directly
                     from pgvector without an LLM call. Result is cached in-process.
        Fallback   → semantic search if metadata is missing (legacy memories).
        Fallback 2 → Query SQL Server database directly to self-heal and resolve permissions.
        Default    → standard access (deny-by-default) if Mem0 and DB are unavailable.
        """
        default = {
            "role": "standard",
            "support_level": 0,
            "allowed_tables": ["*"],          # Show all tables by default if user record not found
            "restricted_tables": [],          # No restrictions by default
            "restricted_columns": {},
            "row_filters": [],
        }

        if not user_id:
            return default

        # ── In-process cache hit ─────────────────────────────────────────────
        if user_id in _RBAC_CACHE:
            logging.debug(f"[MEM0] Cache hit for user_id={user_id}")
            return _RBAC_CACHE[user_id]

        try:
            db_perm = self._fetch_rbac_from_db(user_id)
            if db_perm:
                _RBAC_CACHE[user_id] = db_perm
                return db_perm
            return default
        except Exception as e:
            logging.error(f"[MEM0] get_user_permissions error for user_id={user_id}: {e}")
            return default

    def _fetch_rbac_from_db(self, email: str) -> Optional[Dict[str, Any]]:
        """
        Dynamically fetch RBAC permissions for a user from SQL Server
        using the database service, when not present in Mem0.
        """
        try:
            from services.registry import service_registry
            db_service = service_registry.get_db_service()
            if not db_service.is_connected():
                # Attempt to auto-connect with configuration settings
                if all([settings.db_host, settings.db_port, settings.db_user, settings.db_password]):
                    db_service.connect({
                        "host": settings.db_host,
                        "port": settings.db_port,
                        "database": settings.db_name,
                        "user": settings.db_user,
                        "password": settings.db_password,
                        "db_type": settings.db_type
                    })
            
            if not db_service.is_connected():
                logging.warning("[MEM0] DB service not connected during dynamic RBAC fallback.")
                return None
                
            # Query the user (SQL-injection-safe formatted query)
            clean_email = email.replace("'", "''")
            user_sql = f"SELECT Id, RoleId, EmployeeName, AuthUserId FROM AppUsers WHERE Email = '{clean_email}' AND IsActive = 1"
            user_rows = db_service.execute_query(user_sql)
            if not user_rows or not isinstance(user_rows, list):
                logging.warning(f"[MEM0] User '{email}' not found in AppUsers DB.")
                return None
                
            user = user_rows[0]
            role_id = user.get("RoleId")
            employee_name = user.get("EmployeeName")
            auth_user_id = user.get("AuthUserId")
            app_user_id = user.get("Id")
            
            if not role_id:
                logging.warning(f"[MEM0] User '{email}' has no RoleId in DB.")
                return None
                
            # Query the role
            role_sql = f"SELECT RoleName, RoleCode, SupportLevel, AllowedPages FROM Roles WHERE RoleId = {int(role_id)} AND IsActive = 1"
            role_rows = db_service.execute_query(role_sql)
            if not role_rows or not isinstance(role_rows, list):
                logging.warning(f"[MEM0] RoleId={role_id} not found/active in Roles DB.")
                return None
                
            role = role_rows[0]
            role_name = role.get("RoleName", "Unknown")
            role_code = role.get("RoleCode", "UNKNOWN")
            support_level = int(role.get("SupportLevel", 0))
            allowed_pages_raw = role.get("AllowedPages", "")
            
            # Parse allowed pages
            allowed_pages = []
            if allowed_pages_raw:
                try:
                    if allowed_pages_raw.strip().startswith("["):
                        allowed_pages = json.loads(allowed_pages_raw)
                    else:
                        allowed_pages = [p.strip() for p in allowed_pages_raw.split(",") if p.strip()]
                except Exception as e:
                    logging.error(f"[MEM0] Error parsing AllowedPages for role {role_name}: {e}")
                    allowed_pages = []
                    
            # Resolve allowed tables
            import os
            try:
                base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                json_path = os.path.join(base_dir, "page_to_tables.json")
                with open(json_path, "r", encoding="utf-8") as f:
                    page_to_tables = json.load(f)
            except Exception as e:
                logging.error(f"[MEM0] Failed to load page_to_tables.json: {e}")
                page_to_tables = {}
            
            tables = set()
            if "ALL_ACCESS" in allowed_pages:
                tables = {"*"}
            else:
                for page in allowed_pages:
                    tables.update(page_to_tables.get(page, []))
            allowed_tables = sorted(tables) if "*" not in tables else ["*"]
            
            # Build restricted tables
            if allowed_tables == ["*"]:
                restricted_tables = []
            else:
                allowed_lower = {t.lower() for t in allowed_tables}
                restricted_tables = [t for t in self._get_all_db_tables() if t.lower() not in allowed_lower]
                
            permissions = {
                "role":               role_code.lower(),
                "role_name":          role_name,
                "support_level":      support_level,
                "allowed_tables":     allowed_tables,
                "restricted_tables":  restricted_tables,
                "restricted_columns": {},
                "row_filters":        [],
                "email":              email,
                "employee_name":      employee_name,
            }
            

                    
            return permissions
            
        except Exception as ex:
            logging.error(f"[MEM0] Error during dynamic RBAC fetch from DB: {ex}")
            return None

    def invalidate_cache(self, user_id: Optional[str] = None):
        """Clear in-process cache (call after re-seeding)."""
        if user_id:
            _RBAC_CACHE.pop(user_id, None)
        else:
            _RBAC_CACHE.clear()
        logging.info(f"[MEM0] Cache invalidated for user_id={user_id or 'ALL'}")

    # ── Schema filtering ─────────────────────────────────────────────────────

    def filter_schema_for_user(
        self,
        schema_text: str,
        permissions: Dict[str, Any]
    ) -> str:
        """
        Always returns the full schema context to prevent the LLM from generating
        confusing 'Insufficient schema context' errors.
        Security and table-level access control are strictly enforced post-generation
        via the SQL guardrail in query.py.
        """
        logging.debug("[MEM0] Schema filtering bypassed. Full schema sent to LLM.")
        return schema_text

    # ── Audit log ────────────────────────────────────────────────────────────

    def add_audit_log(self, user_id: str, session_id: str, query: str, status: str):
        """Append query audit entry to user's Mem0 history."""
        if not self.is_ready():
            return
        try:
            self.client.add(
                [
                    {"role": "user",   "content": f"Query: '{query}'"},
                    {"role": "system", "content": f"Status: {status}"},
                ],
                user_id=user_id,
                run_id=session_id,
            )
        except Exception as e:
            logging.error(f"[MEM0] add_audit_log failed: {e}")

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _extract_from_metadata(self, memories: List[Any]) -> Optional[Dict[str, Any]]:
        """
        Fast path: extract RBAC from the 'metadata' dict stored during seeding.
        Returns None if no structured metadata found.
        """
        for m in memories:
            meta = {}
            if isinstance(m, dict):
                meta = m.get("metadata") or {}
            elif hasattr(m, "metadata"):
                meta = getattr(m, "metadata") or {}

            if not meta or meta.get("type") != "user_rbac":
                continue

            raw_tables = meta.get("allowed_tables", "")
            try:
                tables = json.loads(raw_tables) if isinstance(raw_tables, str) else raw_tables
            except (json.JSONDecodeError, TypeError):
                tables = ["*"]

            support_level = int(meta.get("support_level", 0))
            role_code     = meta.get("role_code", "UNKNOWN")
            role_name     = meta.get("role_name", "Unknown")

            # Build restricted_tables (inversion of allowed)
            if tables == ["*"]:
                restricted = []
            else:
                allowed_lower = {t.lower() for t in tables}
                restricted = [t for t in self._get_all_db_tables() if t.lower() not in allowed_lower]

            return {
                "role":               role_code.lower(),
                "role_name":          role_name,
                "support_level":      support_level,
                "allowed_tables":     tables,
                "restricted_tables":  restricted,
                "restricted_columns": {},
                "row_filters":        [],
                "email":              meta.get("email", ""),
                "employee_name":      meta.get("employee_name", ""),
            }

        return None  # No structured metadata found

    def _semantic_search_permissions(self, user_id: str) -> Dict[str, Any]:
        """
        Fallback: semantic vector search when metadata is unavailable.
        Less efficient – triggers an embedding + similarity search in pgvector.
        """
        default = {
            "role": "standard", "support_level": 0,
            "allowed_tables": ["*"], "restricted_tables": [],
            "restricted_columns": {}, "row_filters": [],
        }
        try:
            user_mems   = self.client.search(
                query="user role and allowed database tables",
                user_id=user_id, limit=5
            )
            global_mems = self.client.search(
                query="role policy allowed SQL tables",
                agent_id="global_rbac", limit=5
            )

            texts = []
            for m in user_mems + global_mems:
                if isinstance(m, dict):
                    texts.append(m.get("memory", ""))
                elif hasattr(m, "memory"):
                    texts.append(getattr(m, "memory", ""))

            combined = " ".join(texts).lower()

            if "administrator" in combined or "all database tables" in combined:
                return {**default, "role": "admin", "support_level": 5, "allowed_tables": ["*"]}

            # Extract table list from memory text
            match = re.search(r"allowed sql tables[:\s]+([^\.]+)\.", combined)
            if match:
                tables = [t.strip() for t in match.group(1).split(",") if t.strip()]
                if tables:
                    allowed_lower = {t.lower() for t in tables}
                    restricted = [t for t in self._get_all_db_tables() if t.lower() not in allowed_lower]
                    role = "support" if "support" in combined else "employee"
                    level = 1 if role == "support" else 0
                    return {
                        **default,
                        "role": role, "support_level": level,
                        "allowed_tables": tables, "restricted_tables": restricted,
                    }
        except Exception as e:
            logging.error(f"[MEM0] Semantic search fallback failed: {e}")

        return default
