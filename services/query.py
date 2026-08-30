from typing import List, Dict, Any, Tuple, Optional
import time
from datetime import datetime

from services.database import DatabaseService
from services.llm import LLMService
from services.billing.billing_service import BillingService
from utils.parsing import extract_sql_queries
import tiktoken
import json
import logging
import re
from config import settings


class QueryService:
    def __init__(self, db_service: DatabaseService, llm_service: LLMService, billing_service: BillingService = None, mongodb_service = None):
        self.db_service = db_service
        self.llm_service = llm_service
        self.billing_service = billing_service
        self.mongodb_service = mongodb_service
        self.query_history = []
        try:
            self.encoding = tiktoken.get_encoding("cl100k_base")
        except Exception:
            self.encoding = None
            
    def count_tokens(self, text: str) -> int:
        """Count tokens in text using tiktoken"""
        if not text or not self.encoding:
            return 0
        return len(self.encoding.encode(text))
        
    def validate_prerequisites(self):
        """Validate that all prerequisites are met"""
        if not self.db_service.is_connected():
            raise ValueError("Database is not connected. Please connect to a database first.")
        
        if not self.llm_service.is_configured():
            config_details = self.llm_service.get_config_details()
            error_msg = "LLM is not configured. Please configure the LLM service first."
            if config_details:
                error_msg += f" Current config state: {config_details}"
            raise ValueError(error_msg)
        
    def _build_history_context(self, session_id: Optional[str], limit: int = 3, token_budget: int = 250) -> str:
        """Build a compact, token-capped summary of prior turns in this session.
        Keeps only question + a short answer snippet per turn (no raw results/SQL),
        and trims the oldest turns first until the block fits token_budget.
        """
        if not session_id:
            return ""
        try:
            prior_turns = self.get_history(limit=limit, session_id=session_id)
        except Exception as e:
            logging.warning(f"[History] Failed to fetch prior turns for session {session_id}: {e}")
            return ""

        if not prior_turns:
            return ""

        lines = []
        for turn in prior_turns:
            question = str(turn.get("query", "")).strip()
            if not question:
                continue
            explanation = str(turn.get("explanation", "") or "").strip()
            snippet = explanation[:150].strip()
            if len(explanation) > 150:
                snippet += "..."
            lines.append(f"Q: {question}\nA: {snippet}" if snippet else f"Q: {question}")

        while lines and self.count_tokens("\n".join(lines)) > token_budget:
            lines.pop(0)

        if not lines:
            return ""

        return "Prior turns in this session (most recent last, for resolving follow-ups only):\n" + "\n".join(lines)

    def process_query(self, user_query: str, max_tokens: int = 4096, temperature: float = 0.0,
                      user_id: str = None, session_id: str = None, message_id: str = None, company_id: str = None,
                      background_tasks: Any = None, task_id: int = None,
                      use_chat_history: bool = False, history_limit: int = 3,
                      include_explanation: bool = True) -> Dict[str, Any]:
        """Process natural language query and return results.
        Flow: schema fetch & filter → SQL generation → auto-repair on error → execution → explanation
        """
        start_time = time.time()

        try:
            self.validate_prerequisites()

            logging.info(f"--- START PROCESSING QUERY: '{user_query[:80]}' ---")

            # Full administrative access to all tables
            permissions = {"role": "admin", "allowed_tables": ["*"], "restricted_tables": [], "row_filters": []}

            db_params = self.db_service.get_connection_params()
            db_name = db_params.get("database", "unknown")
            dialect = self.db_service.db_type

            # ── STEP 1: Fetch schema ────────────────────────────────────────────
            logging.info("[STEP 1] Fetching database schema...")
            input_tokens = self.count_tokens(user_query)
            output_tokens = 0

            schema_context = ""
            try:
                allowed_tables = permissions.get("allowed_tables")
                schema_context = self.db_service.get_simplified_schema(allowed_tables=allowed_tables)
                if schema_context:
                    if allowed_tables is not None and allowed_tables != ["*"]:
                        logging.info(f"[STEP 1] Schema fetched ({len(schema_context)} chars) filtered by task allowed tables: {allowed_tables}")
                    else:
                        logging.info(f"[STEP 1] Schema fetched ({len(schema_context)} chars). Bypassing schema filtering to send full schema to LLM.")
                else:
                    logging.error("[STEP 1] Schema is empty — cannot generate SQL.")
            except Exception as schema_err:
                logging.error(f"[STEP 1] Schema fetch failed: {schema_err}")

            if task_id:
                schema_context = f"these are the table task_id {task_id} is allowed\nthese are the table task_id{task_id} is allowed\n\n" + schema_context

            # Truncate if oversized
            if len(schema_context) > settings.llm_max_context_chars:
                logging.info(f"[STEP 1] Truncating schema from {len(schema_context)} → {settings.llm_max_context_chars} chars.")
                schema_context = schema_context[:settings.llm_max_context_chars] + "\n[...schema truncated...]"

            logging.info(f"[STEP 1] Schema sent to LLM:\n{schema_context}\n{'─'*60}")

            # ── Meta-query injection ────────────────────────────────────────────
            # If the user is asking about DB structure, prepend information_schema hints
            if self._detect_meta_query(user_query):
                meta_context = self._get_meta_context(db_name, dialect)
                schema_context = meta_context + "\n\n" + schema_context
                logging.info("[STEP 1] Meta-query detected — injected information_schema context.")

            # ── STEP 2: Generate SQL ────────────────────────────────────────────
            logging.info(f"[STEP 2] Generating {dialect.upper()} SQL...")
            sql_gen_chain = self.llm_service.create_sql_generation_chain(dialect=dialect)

            # Inject Row-level Filter constraints
            augmented_query = user_query
            if permissions.get("role") != "admin" and permissions.get("row_filters"):
                filter_str = " AND ".join(permissions["row_filters"])
                augmented_query += f"\n(CONSTRAINT: Ensure the generated SQL only returns records satisfying: {filter_str})"

            if task_id and permissions.get("allowed_tables") and permissions["allowed_tables"] != ["*"]:
                allowed_tables_str = ", ".join(permissions["allowed_tables"])
                allowed_list_quoted = ", ".join(f"'{t}'" for t in permissions["allowed_tables"])
                augmented_query += (
                    f"\n(STRICT CONSTRAINT: You MUST only use and query the following allowed tables for task {task_id}: {allowed_tables_str}. "
                    f"Do NOT generate SQL querying any other tables, even if they are listed in system metadata or elsewhere. "
                    f"If you are querying system catalogs/metadata views (like information_schema.tables or information_schema.columns), "
                    f"you MUST append a WHERE filter on the table name column (e.g., table_name IN ({allowed_list_quoted})) "
                    f"so that ONLY the allowed tables are returned in the query results. "
                    f"Never expose or query any other tables under any circumstances.)"
                )

            if use_chat_history:
                history_context = self._build_history_context(session_id, history_limit)
                if history_context:
                    augmented_query = f"{history_context}\n\nCurrent question: {augmented_query}"
                    logging.info(f"[STEP 2] Injected chat history context ({self.count_tokens(history_context)} tokens, up to {history_limit} turns).")

            input_tokens += self.count_tokens(augmented_query) + self.count_tokens(schema_context)

            try:
                generated_text = sql_gen_chain.invoke({
                    "Question": augmented_query,
                    "schema_context": schema_context
                })
                output_tokens += self.count_tokens(str(generated_text))
                raw_output = str(generated_text).strip()
                logging.info(f"[STEP 2] LLM raw output ({len(raw_output)} chars):\n{raw_output}\n{'─'*60}")
                if not raw_output:
                    raise RuntimeError(
                        f"The LLM ({self.llm_service.config_details.get('model', 'unknown') if self.llm_service.config_details else 'unknown'}) "
                        f"returned an empty response. This may happen with reasoning/thinking models. "
                        f"Try a different model or simplify the question."
                    )
                generated_text = raw_output
            except Exception as sql_err:
                err_str = str(sql_err)
                logging.error(f"[STEP 2] SQL generation failed: {err_str}")
                cfg = self.llm_service.config_details or {}
                llm_base = cfg.get("base_url", "the configured LLM server")
                configured_model = cfg.get("model", "unknown")
                if any(x in err_str for x in ["Connection error", "Connection refused", "10061", "NewConnectionError"]):
                    raise RuntimeError(f"LLM server unreachable at '{llm_base}'. Check if the service is running.")
                if "404" in err_str and ("not found" in err_str.lower() or "model" in err_str.lower()):
                    c = self.llm_service.config_details
                    if c and c.get("model") != settings.llm_model_name:
                        logging.warning(f"⚠️ Auto-reverting model to '{settings.llm_model_name}' due to 404.")
                        self.llm_service.configure(c.get("api_key"), c.get("base_url"), settings.llm_model_name, c.get("headers"), False)
                        raise RuntimeError(f"Self-healed LLM config to '{settings.llm_model_name}'. Please re-run your query.")
                    raise RuntimeError(f"Model '{configured_model}' not found on '{llm_base}'. Please re-configure.")
                raise RuntimeError(f"SQL generation failed: {err_str}")

            sql_queries = extract_sql_queries(str(generated_text))
            if not sql_queries or "Insufficient schema context" in str(generated_text):
                if self._detect_meta_query(user_query):
                    logging.info("[STEP 2] Meta-query detected with non-executable LLM text — auto-providing metadata catalog query.")
                    if dialect in ("mssql", "sqlserver"):
                        sql_queries = ["SELECT TABLE_SCHEMA, TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'BASE TABLE' ORDER BY TABLE_SCHEMA, TABLE_NAME"]
                    elif dialect in ("mysql", "mariadb"):
                        sql_queries = [f"SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = '{db_name}' AND TABLE_TYPE = 'BASE TABLE' ORDER BY TABLE_NAME"]
                    else:
                        sql_queries = ["SELECT table_schema, table_name FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog', 'information_schema') AND table_type = 'BASE TABLE' ORDER BY table_schema, table_name"]
                else:
                    if not sql_queries:
                        raise ValueError(f"No SQL queries extracted from LLM response for '{db_name}'.")

            logging.info(f"[STEP 2] Extracted {len(sql_queries)} SQL queries.")

            # Post-Generation Guardrail: block SQL referencing tables outside allowed list
            allowed_tables = permissions.get("allowed_tables", ["*"])
            try:
                db_tables = self.db_service.get_tables()
            except Exception:
                db_tables = []

            if allowed_tables is not None and allowed_tables != ["*"]:
                allowed_lower = {t.lower() for t in allowed_tables}
                for sql in sql_queries:
                    for table in db_tables:
                        if table.lower() not in allowed_lower:
                            if re.search(rf"\b{re.escape(table)}\b", sql, re.IGNORECASE):
                                error_msg_rbac = f"Access Denied: You do not have permission to query table."
                                logging.warning(f"[RBAC] BLOCKED user={user_id} | table='{table}' | sql={sql[:80]}")
                                raise ValueError(error_msg_rbac)
            elif permissions.get("role") != "admin" and permissions.get("restricted_tables"):
                for sql in sql_queries:
                    for restricted_table in permissions["restricted_tables"]:
                        if re.search(rf"\b{restricted_table}\b", sql, re.IGNORECASE):
                            error_msg_rbac = f"Access Denied: Query attempts to read restricted table ."
                            logging.warning(f"[RBAC] User {user_id} blocked: restricted table '{restricted_table}'.")
                            raise ValueError(error_msg_rbac)

            # ── STEP 3: Execute SQL (with one auto-repair retry) ────────────────
            logging.info(f"[STEP 3] Executing {len(sql_queries)} queries against '{db_name}'...")
            results = []
            final_sql_queries = list(sql_queries)  # may be replaced by repaired versions

            for i, query in enumerate(final_sql_queries):
                logging.info(f"   → Q{i+1}: {query[:120]}")
                try:
                    query_result = self.db_service.execute_query(query)
                except Exception as exec_err:
                    error_msg = str(exec_err)
                    logging.warning(f"[STEP 3] Q{i+1} failed: {error_msg}. Attempting auto-repair...")

                    try:
                        repair_chain = self.llm_service.create_sql_repair_chain(dialect=dialect)
                        repaired_sql = repair_chain.invoke({
                            "Question": augmented_query,
                            "schema_context": schema_context,
                            "failed_sql": query,
                            "error_message": error_msg
                        })
                        output_tokens += self.count_tokens(str(repaired_sql))
                        repaired_queries = extract_sql_queries(str(repaired_sql))
                        if repaired_queries:
                            repaired_query = repaired_queries[0]
                            logging.info(f"[STEP 3] Repaired SQL:\n{repaired_query}")
                            
                            # Post-Generation Guardrail Check on Repaired SQL output
                            allowed_tables = permissions.get("allowed_tables", ["*"])
                            if allowed_tables is not None and allowed_tables != ["*"]:
                                allowed_lower = {t.lower() for t in allowed_tables}
                                for table in db_tables:
                                    if table.lower() not in allowed_lower:
                                        if re.search(rf"\b{re.escape(table)}\b", repaired_query, re.IGNORECASE):
                                            error_msg_rbac = f"Access Denied: You do not have permission to query table."
                                            logging.warning(f"[RBAC] BLOCKED user={user_id} | table='{table}' | sql={repaired_query[:80]}")
                                            raise ValueError(error_msg_rbac)

                            if permissions.get("role") != "admin" and permissions.get("restricted_tables"):
                                for restricted_table in permissions["restricted_tables"]:
                                    if re.search(rf"\b{restricted_table}\b", repaired_query, re.IGNORECASE):
                                        error_msg_rbac = f"Access Denied: Repaired query attempts to read restricted table ."
                                        logging.warning(f"[RBAC] User {user_id} blocked: repaired query tried to access restricted table '{restricted_table}'. SQL: {repaired_query}")
                                        raise ValueError(error_msg_rbac)
                                        
                            query_result = self.db_service.execute_query(repaired_query)
                            final_sql_queries[i] = repaired_query  # record the repaired version
                            logging.info(f"[STEP 3] Repaired query executed successfully.")
                        else:
                            raise RuntimeError("Repair chain returned no valid SQL.")
                    except Exception as repair_err:
                        logging.error(f"[STEP 3] Auto-repair also failed: {repair_err}")
                        raise RuntimeError(
                            f"Query execution failed and could not be auto-repaired.\n"
                            f"Original error: {error_msg}\nRepair error: {repair_err}"
                        )

                # Normalise result format
                query_result = self._filter_metadata_results(query_result, allowed_tables)
                if isinstance(query_result, (list, dict)):
                    results.append(query_result)
                else:
                    results.append({"raw_result": str(query_result)})

            logging.info("[STEP 3] All queries executed successfully.")

            # ── STEP 4: Generate explanation (optional, to save tokens) ─────────
            if include_explanation:
                logging.info("[STEP 4] Generating natural language explanation...")
                explanation_chain = self.llm_service.create_explanation_chain()
                input_tokens += self.count_tokens(user_query) + self.count_tokens(schema_context)
                explanation = explanation_chain.invoke({
                    "Question": user_query,
                    "schema_info": schema_context,
                    "results": str(results)
                })
                output_tokens += self.count_tokens(str(explanation))
            else:
                logging.info("[STEP 4] Explanation generation disabled by request — skipping.")
                explanation = ""
            logging.info("--- FINISHED PROCESSING QUERY ---")



            # ── Build response ──────────────────────────────────────────────────
            execution_time = time.time() - start_time
            billing_info = None
            if self.billing_service:
                billing_info = self.billing_service.calculate_cost(input_tokens, output_tokens, user_id, session_id)

            response = {
                "query": user_query,
                "sql_queries": [{"sql": final_sql_queries[i], "order": i} for i in range(len(final_sql_queries))],
                "results": results,
                "explanation": explanation,
                "timestamp": datetime.now(),
                "execution_time": execution_time,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
                "billing": billing_info,
                "user_id": user_id,
                "session_id": session_id,
                "message_id": message_id,
                "company_id": company_id,
                "task_id": task_id
            }

            self.query_history.append(response)

            if self.mongodb_service:
                if background_tasks:
                    try:
                        background_tasks.add_task(self.mongodb_service.save_result, response)
                        logging.info("[INFO] Result scheduled to be saved to MongoDB in background via FastAPI BackgroundTasks.")
                    except Exception as e:
                        logging.error(f"[ERROR] Failed to schedule background task for MongoDB save: {e}")
                else:
                    # Fallback to background thread if background_tasks is not provided (e.g., in ThreadPoolExecutor)
                    try:
                        import threading
                        def save_bg(mongodb_svc, resp):
                            try:
                                mongodb_svc.save_result(resp)
                            except Exception as th_err:
                                logging.error(f"[ERROR] Failed to save to MongoDB in background thread: {th_err}")
                        
                        threading.Thread(target=save_bg, args=(self.mongodb_service, response), daemon=True).start()
                        logging.info("[INFO] Result scheduled to be saved to MongoDB in background thread.")
                    except Exception as thread_err:
                        logging.error(f"[ERROR] Failed to spawn background thread for MongoDB save: {thread_err}")

            logging.info(f"[INFO] Done in {execution_time:.2f}s | Tokens: in={input_tokens} out={output_tokens}")
            return response

        except Exception as e:
            logging.error(f"[ERROR] process_query failed: {e}")
            raise

            
    async def stream_query(self, user_query: str, max_tokens: int = 4096, temperature: float = 0.0,
                          user_id: str = None, session_id: str = None, message_id: str = None, company_id: str = None,
                          task_id: int = None, use_chat_history: bool = False, history_limit: int = 3,
                          include_explanation: bool = True):
        """Process natural language query and stream results chunk by chunk.
        Enforces schema discovery, RBAC, meta-query injection, auto-repair, explanation streaming, auditing, and persistence.
        """
        start_time = time.time()
        input_tokens = self.count_tokens(user_query)
        output_tokens = 0
        
        try:
            # 1. Validation & Initialization
            self.validate_prerequisites()
            yield json.dumps({"type": "status", "content": "Analyzing query and discovering schema..."}) + "\n"
            
            # Full administrative access to all tables
            permissions = {"role": "admin", "allowed_tables": ["*"], "restricted_tables": [], "row_filters": []}

            db_params = self.db_service.get_connection_params()
            db_name = db_params.get("database", "unknown")
            dialect = self.db_service.db_type

            # Fetch simplified schema
            allowed_tables = permissions.get("allowed_tables")
            schema_context = self.db_service.get_simplified_schema(allowed_tables=allowed_tables)
            if not schema_context:
                yield json.dumps({"type": "status", "content": "Falling back to database schema..."}) + "\n"
                schema_context = self.db_service.get_simplified_schema(allowed_tables=allowed_tables)

            if task_id:
                schema_context = f"these are the table task_id {task_id} is allowed\nthese are the table task_id{task_id} is allowed\n\n" + schema_context

            # Truncate if oversized
            if len(schema_context) > settings.llm_max_context_chars:
                logging.info(f"[STEP 1] Truncating schema from {len(schema_context)} → {settings.llm_max_context_chars} chars.")
                schema_context = schema_context[:settings.llm_max_context_chars] + "\n[...schema truncated...]"

            # Meta-query injection
            if self._detect_meta_query(user_query):
                meta_context = self._get_meta_context(db_name, dialect)
                schema_context = meta_context + "\n\n" + schema_context
                logging.info("[STEP 1] Meta-query detected — injected information_schema context.")

            # SQL Generation
            yield json.dumps({"type": "status", "content": f"Generating {dialect.upper()} query..."}) + "\n"
            sql_gen_chain = self.llm_service.create_sql_generation_chain(dialect=dialect)

            augmented_query = user_query
            if permissions.get("role") != "admin" and permissions.get("row_filters"):
                filter_str = " AND ".join(permissions["row_filters"])
                augmented_query += f"\n(CONSTRAINT: Ensure the generated SQL only returns records satisfying: {filter_str})"

            if task_id and permissions.get("allowed_tables") and permissions["allowed_tables"] != ["*"]:
                allowed_tables_str = ", ".join(permissions["allowed_tables"])
                allowed_list_quoted = ", ".join(f"'{t}'" for t in permissions["allowed_tables"])
                augmented_query += (
                    f"\n(STRICT CONSTRAINT: You MUST only use and query the following allowed tables for task {task_id}: {allowed_tables_str}. "
                    f"Do NOT generate SQL querying any other tables, even if they are listed in system metadata or elsewhere. "
                    f"If you are querying system catalogs/metadata views (like information_schema.tables or information_schema.columns), "
                    f"you MUST append a WHERE filter on the table name column (e.g., table_name IN ({allowed_list_quoted})) "
                    f"so that ONLY the allowed tables are returned in the query results. "
                    f"Never expose or query any other tables under any circumstances.)"
                )

            if use_chat_history:
                history_context = self._build_history_context(session_id, history_limit)
                if history_context:
                    augmented_query = f"{history_context}\n\nCurrent question: {augmented_query}"
                    logging.info(f"[STREAM] Injected chat history context ({self.count_tokens(history_context)} tokens, up to {history_limit} turns).")

            input_tokens += self.count_tokens(augmented_query) + self.count_tokens(schema_context)

            try:
                generated_text = await sql_gen_chain.ainvoke({
                    "Question": augmented_query,
                    "schema_context": schema_context
                })
                output_tokens += self.count_tokens(str(generated_text))
                raw_output = str(generated_text).strip()
                if not raw_output:
                    raise RuntimeError(
                        f"The LLM returned an empty response. This may happen with reasoning/thinking models."
                    )
                generated_text = raw_output
            except Exception as sql_err:
                err_str = str(sql_err)
                logging.error(f"[STREAM] SQL generation failed: {err_str}")
                cfg = self.llm_service.config_details or {}
                llm_base = cfg.get("base_url", "the configured LLM server")
                configured_model = cfg.get("model", "unknown")
                if any(x in err_str for x in ["Connection error", "Connection refused", "10061", "NewConnectionError"]):
                    raise RuntimeError(f"LLM server unreachable at '{llm_base}'. Check if the service is running.")
                if "404" in err_str and ("not found" in err_str.lower() or "model" in err_str.lower()):
                    c = self.llm_service.config_details
                    if c and c.get("model") != settings.llm_model_name:
                        logging.warning(f"⚠️ Auto-reverting model to '{settings.llm_model_name}' due to 404.")
                        self.llm_service.configure(c.get("api_key"), c.get("base_url"), settings.llm_model_name, c.get("headers"), False)
                        raise RuntimeError(f"Self-healed LLM config to '{settings.llm_model_name}'. Please re-run your query.")
                    raise RuntimeError(f"Model '{configured_model}' not found on '{llm_base}'. Please re-configure.")
                raise RuntimeError(f"SQL generation failed: {err_str}")

            sql_queries = extract_sql_queries(str(generated_text))
            if not sql_queries:
                raise ValueError(f"No SQL queries extracted from LLM response for '{db_name}'.")

            # Post-Generation Guardrail Check on Generated SQL
            allowed_tables = permissions.get("allowed_tables", ["*"])
            try:
                db_tables = self.db_service.get_tables()
            except Exception:
                db_tables = []

            if allowed_tables is not None and allowed_tables != ["*"]:
                allowed_lower = {t.lower() for t in allowed_tables}
                for sql in sql_queries:
                    for table in db_tables:
                        if table.lower() not in allowed_lower:
                            if re.search(rf"\b{re.escape(table)}\b", sql, re.IGNORECASE):
                                error_msg_rbac = f"Access Denied: You do not have permission to query table."
                                logging.warning(f"[RBAC] [STREAM] BLOCKED user={user_id} | table='{table}' | sql={sql[:80]}")
                                raise ValueError(error_msg_rbac)
            elif permissions.get("role") != "admin" and permissions.get("restricted_tables"):
                for sql in sql_queries:
                    for restricted_table in permissions["restricted_tables"]:
                        if re.search(rf"\b{restricted_table}\b", sql, re.IGNORECASE):
                            error_msg_rbac = f"Access Denied: Query attempts to read restricted table ."
                            logging.warning(f"[RBAC] [STREAM] User {user_id} blocked: restricted table '{restricted_table}'.")
                            raise ValueError(error_msg_rbac)

            # 4. SQL Execution (with one auto-repair retry)
            yield json.dumps({"type": "status", "content": "Executing SQL and retrieving data..."}) + "\n"
            results = []
            final_sql_queries = list(sql_queries)

            for i, query in enumerate(final_sql_queries):
                try:
                    query_result = self.db_service.execute_query(query)
                except Exception as exec_err:
                    error_msg = str(exec_err)
                    logging.warning(f"[STREAM] Q{i+1} failed: {error_msg}. Attempting auto-repair...")
                    yield json.dumps({"type": "status", "content": f"Query execution failed: {error_msg}. Attempting auto-repair..."}) + "\n"

                    try:
                        repair_chain = self.llm_service.create_sql_repair_chain(dialect=dialect)
                        repaired_sql = await repair_chain.ainvoke({
                            "Question": augmented_query,
                            "schema_context": schema_context,
                            "failed_sql": query,
                            "error_message": error_msg
                        })
                        output_tokens += self.count_tokens(str(repaired_sql))
                        repaired_queries = extract_sql_queries(str(repaired_sql))
                        if repaired_queries:
                            repaired_query = repaired_queries[0]
                            logging.info(f"[STREAM] Repaired SQL:\n{repaired_query}")
                            
                            # Post-Generation Guardrail Check on Repaired SQL
                            allowed_tables = permissions.get("allowed_tables", ["*"])
                            if allowed_tables is not None and allowed_tables != ["*"]:
                                allowed_lower = {t.lower() for t in allowed_tables}
                                for table in db_tables:
                                    if table.lower() not in allowed_lower:
                                        if re.search(rf"\b{re.escape(table)}\b", repaired_query, re.IGNORECASE):
                                            error_msg_rbac = f"Access Denied: You do not have permission to query table."
                                            logging.warning(f"[RBAC] [STREAM] BLOCKED user={user_id} | table='{table}' | sql={repaired_query[:80]}")
                                            raise ValueError(error_msg_rbac)

                            if permissions.get("role") != "admin" and permissions.get("restricted_tables"):
                                for restricted_table in permissions["restricted_tables"]:
                                    if re.search(rf"\b{restricted_table}\b", repaired_query, re.IGNORECASE):
                                        error_msg_rbac = f"Access Denied: Repaired query attempts to read restricted table ."
                                        logging.warning(f"[RBAC] [STREAM] User {user_id} blocked: repaired query tried to access restricted table '{restricted_table}'.")
                                        raise ValueError(error_msg_rbac)
                                        
                            query_result = self.db_service.execute_query(repaired_query)
                            final_sql_queries[i] = repaired_query  # record the repaired version
                            logging.info(f"[STREAM] Repaired query executed successfully.")
                        else:
                            raise RuntimeError("Repair chain returned no valid SQL.")
                    except Exception as repair_err:
                        logging.error(f"[STREAM] Auto-repair also failed: {repair_err}")
                        raise RuntimeError(
                            f"Query execution failed and could not be auto-repaired.\n"
                            f"Original error: {error_msg}\nRepair error: {repair_err}"
                        )

                # Normalise result format
                query_result = self._filter_metadata_results(query_result, allowed_tables)
                if isinstance(query_result, (list, dict)):
                    results.append(query_result)
                else:
                    results.append({"raw_result": str(query_result)})

            yield json.dumps({"type": "sql", "content": final_sql_queries}) + "\n"
            yield json.dumps({"type": "results", "content": results}) + "\n"

            # 5. Explaining Results (The actual Stream) — optional, to save tokens
            full_explanation = ""
            if include_explanation:
                yield json.dumps({"type": "status", "content": "Generating explanation..."}) + "\n"
                explanation_chain = self.llm_service.create_explanation_chain()

                explanation_input = {
                    "Question": user_query,
                    "schema_info": schema_context,
                    "results": str(results)
                }

                input_tokens += self.count_tokens(user_query) + self.count_tokens(schema_context)

                yield json.dumps({"type": "explanation_start"}) + "\n"
                async for chunk in explanation_chain.astream(explanation_input):
                    full_explanation += chunk
                    yield json.dumps({"type": "explanation_chunk", "content": chunk}) + "\n"

                output_tokens += self.count_tokens(full_explanation)
            else:
                logging.info("[STREAM] Explanation generation disabled by request — skipping.")
                yield json.dumps({"type": "explanation_start"}) + "\n"
            


            # Calculate billing info
            execution_time = time.time() - start_time
            billing_info = None
            if self.billing_service:
                billing_info = self.billing_service.calculate_cost(input_tokens, output_tokens, user_id, session_id)

            # Build full response object for persistence & history
            response = {
                "query": user_query,
                "sql_queries": [{"sql": final_sql_queries[i], "order": i} for i in range(len(final_sql_queries))],
                "results": results,
                "explanation": full_explanation,
                "timestamp": datetime.now(),
                "execution_time": execution_time,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
                "billing": billing_info,
                "user_id": user_id,
                "session_id": session_id,
                "message_id": message_id,
                "company_id": company_id,
                "task_id": task_id
            }

            self.query_history.append(response)

            # Save to MongoDB asynchronously
            if self.mongodb_service:
                try:
                    import threading
                    def save_bg(mongodb_svc, resp):
                        try:
                            mongodb_svc.save_result(resp)
                        except Exception as th_err:
                            logging.error(f"[ERROR] [STREAM] Failed to save to MongoDB in background thread: {th_err}")
                    
                    threading.Thread(target=save_bg, args=(self.mongodb_service, response), daemon=True).start()
                    logging.info("[INFO] [STREAM] Result scheduled to be saved to MongoDB in background thread.")
                except Exception as thread_err:
                    logging.error(f"[ERROR] [STREAM] Failed to spawn background thread for MongoDB save: {thread_err}")

            # Yield final metadata matching QueryResult schema
            yield json.dumps({
                "type": "metadata",
                "session_id": session_id,
                "message_id": message_id,
                "company_id": company_id,
                "query": user_query,
                "sql_queries": [{"sql": final_sql_queries[i], "order": i} for i in range(len(final_sql_queries))],
                "results": results,
                "explanation": full_explanation,
                "timestamp": datetime.now().isoformat(),
                "execution_time": execution_time,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
                "billing": billing_info,
                "user_id": user_id,
                "task_id": task_id
            }) + "\n"

        except Exception as e:
            logging.error(f"Streaming query failed: {e}")
            yield json.dumps({"type": "error", "content": str(e)}) + "\n"

    def _detect_meta_query(self, query: str) -> bool:
        """Detect if the query is asking about the database structure itself (metadata)."""
        meta_keywords = [
            # tables — all common phrasings
            "number of tables", "how many tables", "list tables", "list table",
            "all tables", "all the tables", "what are all the tables",
            "what are the tables", "tables in the db", "tables in the database",
            "tables exist", "available tables", "existing tables",
            "show tables", "show table", "what tables", "which tables",
            "tables available", "tables do we have", "tables are there", "table list",
            # columns
            "all the columns", "list columns", "list column", "show columns",
            "show column", "what columns", "which columns", "all columns",
            "column names", "column name",
            # schemas / structure
            "list schemas", "list schema", "all schemas", "database schema", "schema list",
            "schema of", "show schema", "view schema", "db schema", "the schema", "schema",
            "database size", "database version", "db structure", "structure of",
            "metadata", "structure", "describe table", "describe tables",
        ]
        q_lower = query.lower()
        return any(kw in q_lower for kw in meta_keywords)

    def _get_meta_context(self, db_name: str, dialect: str = "postgresql") -> str:
        """Provide dialect-aware context for metadata queries (information_schema)."""
        dialect = (dialect or "postgresql").lower()

        if dialect in ("sqlserver", "mssql"):
            return f"""-- METADATA QUERY CONTEXT for database '{db_name}' (SQL Server)
-- Use these system catalog views to answer structural questions:
--   INFORMATION_SCHEMA.TABLES      : TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE
--   INFORMATION_SCHEMA.COLUMNS     : TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE, IS_NULLABLE
--   sys.tables                     : name, object_id, schema_id
--   sys.columns                    : name, object_id, column_id, user_type_id
--
-- Examples:
--   All tables:   SELECT TABLE_SCHEMA, TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'BASE TABLE' ORDER BY TABLE_SCHEMA, TABLE_NAME
--   All columns:  SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = 'dbo' ORDER BY TABLE_NAME, ORDINAL_POSITION
--   Row counts:   SELECT t.name AS table_name, p.rows AS row_count FROM sys.tables t JOIN sys.partitions p ON t.object_id = p.object_id WHERE p.index_id IN (0,1) ORDER BY p.rows DESC"""

        elif dialect in ("mysql", "mariadb"):
            return f"""-- METADATA QUERY CONTEXT for database '{db_name}' (MySQL)
-- Use these system catalog views:
--   INFORMATION_SCHEMA.TABLES   : TABLE_SCHEMA, TABLE_NAME, TABLE_ROWS
--   INFORMATION_SCHEMA.COLUMNS  : TABLE_NAME, COLUMN_NAME, DATA_TYPE, IS_NULLABLE
--
-- Examples:
--   All tables:   SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = '{db_name}'
--   All columns:  SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = '{db_name}' ORDER BY TABLE_NAME, ORDINAL_POSITION"""

        elif dialect in ("oracle",):
            return f"""-- METADATA QUERY CONTEXT for database '{db_name}' (Oracle)
-- Use these catalog views:
--   ALL_TABLES  : OWNER, TABLE_NAME, NUM_ROWS
--   ALL_COLUMNS : OWNER, TABLE_NAME, COLUMN_NAME, DATA_TYPE
--
-- Examples:
--   All tables:   SELECT OWNER, TABLE_NAME FROM ALL_TABLES ORDER BY OWNER, TABLE_NAME
--   All columns:  SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE FROM ALL_TAB_COLUMNS ORDER BY TABLE_NAME, COLUMN_ID"""

        else:  # postgresql default
            return f"""-- METADATA QUERY CONTEXT for database '{db_name}' (PostgreSQL)
-- Use these system catalog views to answer structural questions:
--   information_schema.tables   : table_schema, table_name, table_type
--   information_schema.columns  : table_schema, table_name, column_name, data_type, is_nullable
--   pg_stat_user_tables         : schemaname, relname, n_live_tup (estimated row count)
--
-- Examples:
--   Count tables: SELECT count(*) FROM information_schema.tables WHERE table_schema NOT IN ('information_schema','pg_catalog')
--   All columns:  SELECT table_name, column_name, data_type FROM information_schema.columns WHERE table_schema = 'public' ORDER BY table_name, ordinal_position
--   Row counts:   SELECT relname AS table_name, n_live_tup AS estimated_rows FROM pg_stat_user_tables ORDER BY n_live_tup DESC"""

    def _format_schema_capsules(self, nodes: List[Dict[str, Any]], db_name: str) -> str:
        """Format retrieved nodes as compressed schema capsules for high-scale reasoning"""
        if not nodes:
            return ""
            
        context = f"Retrieved connected subgraph for database '{db_name}':\n\n"
        for node in nodes:
            name = node.get('table_name', 'unknown')
            full_name = node.get('full_name', f"public.{name}")
            role = node.get('role', 'anchor' if node.get('score', 0) > 100 else 'bridge/lookup')
            
            # Identify columns
            cols = node.get('columns', [])
            col_list = ", ".join([f"{c['name']} ({c['type']})" for c in cols[:15]])
            
            context += f"Table: {full_name}\n"
            context += f"Role: {role.upper()}\n"
            context += f"Columns: {col_list}\n"
            if 'estimated_rows' in node:
                context += f"Est. Rows: {node['estimated_rows']}\n"
            context += "---\n"
        return context

    def get_history(self, limit: int = 10, message_id: Optional[str] = None, session_id: Optional[str] = None, company_id: Optional[str] = None, task_id: Optional[int] = None, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get query history. Falls back to MongoDB if available for persistent history."""
        # Try to get from MongoDB for persistent history
        if self.mongodb_service and hasattr(self.mongodb_service, "is_ready") and self.mongodb_service.is_ready():
            try:
                mongo_history = self.mongodb_service.get_history(
                    limit=limit,
                    message_id=message_id,
                    session_id=session_id,
                    company_id=company_id,
                    task_id=task_id,
                    user_id=user_id
                )
                if mongo_history:
                    return mongo_history
            except Exception as e:
                print(f"[ERROR] Failed to fetch history from MongoDB: {e}")
        elif self.mongodb_service:
            # Try calling without is_ready check in case of legacy connection wrapper
            try:
                mongo_history = self.mongodb_service.get_history(
                    limit=limit,
                    message_id=message_id,
                    session_id=session_id,
                    company_id=company_id,
                    task_id=task_id,
                    user_id=user_id
                )
                if mongo_history:
                    return mongo_history
            except Exception as e:
                pass
        
        # Fallback to in-memory history
        results = self.query_history
        if message_id:
            results = [r for r in results if r.get("message_id") == message_id]
        if session_id:
            results = [r for r in results if r.get("session_id") == session_id]
        if company_id:
            results = [r for r in results if r.get("company_id") == company_id]
        if task_id:
            results = [r for r in results if r.get("task_id") == task_id]
        if user_id:
            results = [r for r in results if str(r.get("user_id")) == str(user_id)]
            
        return results[-limit:] if results else []
    
    def clear_history(self):
        """Clear query history"""
        self.query_history = []
    
    def get_result_by_index(self, index: int) -> Dict[str, Any]:
        """Get query result by index from history"""
        if index < 0 or index >= len(self.query_history):
            raise ValueError(f"Invalid index {index}. History has {len(self.query_history)} items.")
        return self.query_history[index]
    
    def get_latest_result(self) -> Dict[str, Any]:
        """Get the latest query result"""
        if not self.query_history:
            raise ValueError("No query results in history")
        return self.query_history[-1]

    def _apply_schema_rbac(self, schema_context: str, restricted_tables: List[str]) -> str:
        """
        Parses the simplified schema text and removes any blocks associated with
        restricted tables to hide columns and indices from SQL generation.
        """
        if not schema_context or not restricted_tables:
            return schema_context
            
        lines = schema_context.split("\n")
        filtered_lines = []
        skip_block = False
        
        for line in lines:
            if line.startswith("Table:") or line.startswith("CREATE TABLE"):
                skip_block = False
                for table in restricted_tables:
                    if f".{table}" in line or f" {table}" in line or line.endswith(table):
                        skip_block = True
                        break
            
            if not skip_block:
                filtered_lines.append(line)
                
        return "\n".join(filtered_lines)

    def _filter_metadata_results(self, query_result: Any, allowed_tables: Optional[List[str]]) -> Any:
        """Filter out any metadata/information_schema results that expose unauthorized tables."""
        if allowed_tables is None or allowed_tables == ["*"] or not isinstance(query_result, list):
            return query_result
            
        allowed_lower = {t.lower() for t in allowed_tables}
        filtered_rows = []
        for row in query_result:
            if isinstance(row, dict):
                is_unauthorized = False
                for k, v in row.items():
                    if k.lower() in ("table_name", "relname", "table"):
                        if str(v).lower() not in allowed_lower:
                            is_unauthorized = True
                            break
                if is_unauthorized:
                    continue
            filtered_rows.append(row)
        return filtered_rows