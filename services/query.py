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


def _extract_invalid_identifier_hint(error_message: str) -> Optional[str]:
    """Best-effort extraction of the invalid table/column identifier from a DB error
    message, so the repair prompt can be given an explicit correction target instead
    of just the raw driver error text."""
    patterns = [
        r'column ["\']?([\w\.]+)["\']? does not exist',       # PostgreSQL column
        r'relation ["\']?([\w\.]+)["\']? does not exist',     # PostgreSQL table
        r'[Uu]nknown column ["\']?([\w\.]+)["\']?',            # MySQL/MariaDB column
        r"[Tt]able ['\"]?([\w\.]+)['\"]? doesn'?t exist",      # MySQL/MariaDB table
        r'[Ii]nvalid column name ["\']?([\w\.]+)["\']?',       # MSSQL column
        r'[Ii]nvalid object name ["\']?([\w\.]+)["\']?',       # MSSQL table
        r'ORA-00904:\s*"?([\w\."]+)"?\s*:\s*invalid identifier',  # Oracle column
        r'ORA-00942:.*table or view does not exist',           # Oracle table (no identifier captured)
    ]
    for pattern in patterns:
        match = re.search(pattern, error_message)
        if match and match.groups():
            return match.group(1)
    return None


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
        
    def process_query(self, user_query: str, max_tokens: int = 4096, temperature: float = 0.0,
                      user_id: str = None, session_id: str = None, message_id: str = None, company_id: str = None,
                      background_tasks: Any = None, task_id: int = None) -> Dict[str, Any]:
        """Process natural language query and return results.
        Flow: schema fetch → SQL generation → auto-repair on error → execution → explanation
        """
        start_time = time.time()

        try:
            self.validate_prerequisites()

            logging.info(f"--- START PROCESSING QUERY: '{user_query[:80]}' ---")

            db_params = self.db_service.get_connection_params()
            db_name = db_params.get("database", "unknown")
            dialect = self.db_service.db_type

            # ── STEP 1: Fetch schema ────────────────────────────────────────────
            logging.info("[STEP 1] Fetching database schema...")
            input_tokens = self.count_tokens(user_query)
            output_tokens = 0

            allowed_tables, kw_tokens_in, kw_tokens_out = self._narrow_allowed_tables(user_query)
            input_tokens += kw_tokens_in
            output_tokens += kw_tokens_out

            schema_context = ""
            try:
                schema_context = self.db_service.get_simplified_schema(allowed_tables=allowed_tables)
                if schema_context:
                    logging.info(f"[STEP 1] Schema fetched ({len(schema_context)} chars).")
                else:
                    logging.error("[STEP 1] Schema is empty — cannot generate SQL.")
            except Exception as schema_err:
                logging.error(f"[STEP 1] Schema fetch failed: {schema_err}")

            if task_id:
                schema_context = f"task_id: {task_id}\n\n" + schema_context

            # Truncate if oversized
            if len(schema_context) > settings.llm_max_context_chars:
                logging.info(f"[STEP 1] Truncating schema from {len(schema_context)} → {settings.llm_max_context_chars} chars.")
                schema_context = schema_context[:settings.llm_max_context_chars] + "\n[...schema truncated...]"

            logging.info(f"[STEP 1] Schema sent to LLM:\n{schema_context}\n{'─'*60}")

            # ── Meta-query injection ────────────────────────────────────────────
            if self._detect_meta_query(user_query):
                meta_context = self._get_meta_context(db_name, dialect)
                schema_context = meta_context + "\n\n" + schema_context
                logging.info("[STEP 1] Meta-query detected — injected information_schema context.")

            # ── STEP 2: Generate SQL ────────────────────────────────────────────
            logging.info(f"[STEP 2] Generating {dialect.upper()} SQL...")
            sql_gen_chain = self.llm_service.create_sql_generation_chain(dialect=dialect)

            augmented_query = user_query
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
            if not sql_queries:
                raise ValueError(f"No SQL queries extracted from LLM response for '{db_name}'.")

            logging.info(f"[STEP 2] Extracted {len(sql_queries)} SQL queries.")

            # ── STEP 3: Execute SQL (with bounded auto-repair retries) ──────────
            max_repair_attempts = max(0, settings.sql_repair_max_attempts)
            logging.info(f"[STEP 3] Executing {len(sql_queries)} queries against '{db_name}' "
                         f"(up to {max_repair_attempts} repair attempt(s) each)...")
            results = []
            final_sql_queries = list(sql_queries)

            for i, query in enumerate(final_sql_queries):
                logging.info(f"   → Q{i+1}: {query[:120]}")
                current_sql = query
                attempted_sql = [query]
                query_result = None
                last_error = None

                for attempt in range(max_repair_attempts + 1):
                    try:
                        query_result = self.db_service.execute_query(current_sql)
                        final_sql_queries[i] = current_sql
                        last_error = None
                        break
                    except Exception as exec_err:
                        last_error = str(exec_err)
                        if attempt == max_repair_attempts:
                            break

                        logging.warning(f"[STEP 3] Q{i+1} attempt {attempt + 1} failed: {last_error}. "
                                         f"Attempting auto-repair ({attempt + 1}/{max_repair_attempts})...")
                        invalid_ref = _extract_invalid_identifier_hint(last_error)
                        error_for_repair = last_error
                        if invalid_ref:
                            error_for_repair += (
                                f"\n\nCRITICAL HINT: The column/identifier '{invalid_ref}' DOES NOT EXIST in the schema! "
                                f"DO NOT USE '{invalid_ref}' again! Inspect the column list for each table in schema_context above "
                                f"and use ONLY columns that are explicitly declared."
                            )
                        if len(attempted_sql) > 1:
                            error_for_repair += (
                                f"\n\nNote: previous repair attempt tried:\n{attempted_sql[-1]}\n"
                                f"and it failed — do not repeat that exact query."
                            )

                        try:
                            repair_chain = self.llm_service.create_sql_repair_chain(dialect=dialect)
                            repaired_sql = repair_chain.invoke({
                                "Question": augmented_query,
                                "schema_context": schema_context,
                                "failed_sql": current_sql,
                                "error_message": error_for_repair
                            })
                            output_tokens += self.count_tokens(str(repaired_sql))
                            repaired_queries = extract_sql_queries(str(repaired_sql))
                            if not repaired_queries:
                                last_error = f"{last_error}\n(Repair attempt {attempt + 1} returned no valid SQL.)"
                                break
                            current_sql = repaired_queries[0]
                            attempted_sql.append(current_sql)
                            logging.info(f"[STEP 3] Repaired SQL (attempt {attempt + 1}):\n{current_sql}")
                        except Exception as repair_err:
                            last_error = f"{last_error}\nRepair error: {repair_err}"
                            break

                if last_error is not None:
                    logging.error(f"[STEP 3] Q{i+1} failed after {max_repair_attempts} repair attempt(s): {last_error}")
                    raise RuntimeError(
                        f"Query execution failed and could not be auto-repaired after "
                        f"{max_repair_attempts} attempt(s).\nLast error: {last_error}"
                    )

                logging.info(f"[STEP 3] Q{i+1} executed successfully.")

                # Normalize result format
                if isinstance(query_result, (list, dict)):
                    results.append(query_result)
                else:
                    results.append({"raw_result": str(query_result)})

            logging.info("[STEP 3] All queries executed successfully.")

            # ── STEP 4: Generate explanation ────────────────────────────────────
            logging.info("[STEP 4] Generating natural language explanation...")
            explanation_chain = self.llm_service.create_explanation_chain()
            input_tokens += self.count_tokens(user_query) + self.count_tokens(schema_context)
            explanation = explanation_chain.invoke({
                "Question": user_query,
                "schema_info": schema_context,
                "results": str(results)
            })
            output_tokens += self.count_tokens(str(explanation))
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
                          task_id: int = None):
        """Process natural language query and stream results chunk by chunk."""
        start_time = time.time()
        input_tokens = self.count_tokens(user_query)
        output_tokens = 0
        
        try:
            # 1. Validation & Initialization
            self.validate_prerequisites()
            yield json.dumps({"type": "status", "content": "Analyzing query and discovering schema..."}) + "\n"

            db_params = self.db_service.get_connection_params()
            db_name = db_params.get("database", "unknown")
            dialect = self.db_service.db_type

            # Fetch simplified schema (narrowed to relevant tables when possible)
            allowed_tables, kw_tokens_in, kw_tokens_out = self._narrow_allowed_tables(user_query)
            input_tokens += kw_tokens_in
            output_tokens += kw_tokens_out

            schema_context = self.db_service.get_simplified_schema(allowed_tables=allowed_tables)
            if not schema_context:
                yield json.dumps({"type": "status", "content": "Falling back to database schema..."}) + "\n"
                schema_context = self.db_service.get_simplified_schema()

            if task_id:
                schema_context = f"task_id: {task_id}\n\n" + schema_context

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

            # 4. SQL Execution (with bounded auto-repair retries)
            max_repair_attempts = max(0, settings.sql_repair_max_attempts)
            yield json.dumps({"type": "status", "content": "Executing SQL and retrieving data..."}) + "\n"
            results = []
            final_sql_queries = list(sql_queries)

            for i, query in enumerate(final_sql_queries):
                current_sql = query
                attempted_sql = [query]
                query_result = None
                last_error = None

                for attempt in range(max_repair_attempts + 1):
                    try:
                        query_result = self.db_service.execute_query(current_sql)
                        final_sql_queries[i] = current_sql
                        last_error = None
                        break
                    except Exception as exec_err:
                        last_error = str(exec_err)
                        if attempt == max_repair_attempts:
                            break

                        logging.warning(f"[STREAM] Q{i+1} attempt {attempt + 1} failed: {last_error}. "
                                         f"Attempting auto-repair ({attempt + 1}/{max_repair_attempts})...")
                        yield json.dumps({"type": "status", "content": f"Query execution failed: {last_error}. Attempting auto-repair..."}) + "\n"

                        invalid_ref = _extract_invalid_identifier_hint(last_error)
                        error_for_repair = last_error
                        if invalid_ref:
                            error_for_repair += (
                                f"\n\nCRITICAL HINT: The column/identifier '{invalid_ref}' DOES NOT EXIST in the schema! "
                                f"DO NOT USE '{invalid_ref}' again! Inspect the column list for each table in schema_context above "
                                f"and use ONLY columns that are explicitly declared."
                            )
                        if len(attempted_sql) > 1:
                            error_for_repair += (
                                f"\n\nNote: previous repair attempt tried:\n{attempted_sql[-1]}\n"
                                f"and it failed — do not repeat that exact query."
                            )

                        try:
                            repair_chain = self.llm_service.create_sql_repair_chain(dialect=dialect)
                            repaired_sql = await repair_chain.ainvoke({
                                "Question": augmented_query,
                                "schema_context": schema_context,
                                "failed_sql": current_sql,
                                "error_message": error_for_repair
                            })
                            output_tokens += self.count_tokens(str(repaired_sql))
                            repaired_queries = extract_sql_queries(str(repaired_sql))
                            if not repaired_queries:
                                last_error = f"{last_error}\n(Repair attempt {attempt + 1} returned no valid SQL.)"
                                break
                            current_sql = repaired_queries[0]
                            attempted_sql.append(current_sql)
                            logging.info(f"[STREAM] Repaired SQL (attempt {attempt + 1}):\n{current_sql}")
                        except Exception as repair_err:
                            last_error = f"{last_error}\nRepair error: {repair_err}"
                            break

                if last_error is not None:
                    logging.error(f"[STREAM] Q{i+1} failed after {max_repair_attempts} repair attempt(s): {last_error}")
                    raise RuntimeError(
                        f"Query execution failed and could not be auto-repaired after "
                        f"{max_repair_attempts} attempt(s).\nLast error: {last_error}"
                    )

                # Normalize result format
                if isinstance(query_result, (list, dict)):
                    results.append(query_result)
                else:
                    results.append({"raw_result": str(query_result)})

            yield json.dumps({"type": "sql", "content": final_sql_queries}) + "\n"
            yield json.dumps({"type": "results", "content": results}) + "\n"

            # 5. Explaining Results (The actual Stream)
            yield json.dumps({"type": "status", "content": "Generating explanation..."}) + "\n"
            explanation_chain = self.llm_service.create_explanation_chain()
            
            explanation_input = {
                "Question": user_query,
                "schema_info": schema_context,
                "results": str(results)
            }
            
            input_tokens += self.count_tokens(user_query) + self.count_tokens(schema_context)
            
            yield json.dumps({"type": "explanation_start"}) + "\n"
            full_explanation = ""
            async for chunk in explanation_chain.astream(explanation_input):
                full_explanation += chunk
                yield json.dumps({"type": "explanation_chunk", "content": chunk}) + "\n"
            
            output_tokens += self.count_tokens(full_explanation)

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

    def _narrow_allowed_tables(self, user_query: str) -> Tuple[Optional[List[str]], int, int]:
        """Narrow the schema sent to the LLM down to tables relevant to the question.

        get_simplified_schema() caps out at 50 tables (alphabetical order) when
        unfiltered — on a database with hundreds of tables, whatever the question
        actually needs may never be alphabetically early enough to be included, and
        the LLM silently gets no visibility into it at all (no error — it just isn't
        there), which leads to hallucinated table/column names in the generated SQL.

        Returns (allowed_tables, input_tokens_used, output_tokens_used). Returns
        (None, 0, 0) — i.e. no narrowing, falls back to the default unfiltered
        behavior — whenever the table count is small enough that narrowing isn't
        needed, or if anything in this best-effort step fails.
        """
        try:
            all_tables = self.db_service.get_table_names()
        except Exception as e:
            logging.warning(f"[STEP 1] Could not fetch table names for narrowing: {e}")
            return None, 0, 0

        if not all_tables or len(all_tables) <= 50:
            return None, 0, 0

        try:
            keyword_chain = self.llm_service.create_keyword_extraction_chain()
            in_tokens = self.count_tokens(user_query)
            keywords_raw = keyword_chain.invoke({"Question": user_query})
            out_tokens = self.count_tokens(str(keywords_raw))
            keywords = [k.strip().lower() for k in str(keywords_raw).split(",") if k.strip()]
        except Exception as e:
            logging.warning(f"[STEP 1] Keyword extraction for schema narrowing failed: {e}")
            return None, 0, 0

        if not keywords:
            return None, in_tokens, out_tokens

        matched = [t for t in all_tables if any(kw in t.lower() for kw in keywords)]
        if not matched:
            logging.warning(f"[STEP 1] No tables matched narrowing keywords {keywords} out of "
                             f"{len(all_tables)} table(s) — falling back to unfiltered schema.")
            return None, in_tokens, out_tokens

        logging.info(f"[STEP 1] Narrowed schema from {len(all_tables)} to {len(matched)} "
                     f"table(s) via keywords {keywords}: {matched}")
        return matched, in_tokens, out_tokens

    def _detect_meta_query(self, query: str) -> bool:
        """Detect if the query is asking about the database structure itself (metadata)."""
        meta_keywords = [
            "number of tables", "how many tables", "list tables", "list table",
            "all tables", "all the tables", "what are all the tables",
            "what are the tables", "tables in the db", "tables in the database",
            "tables exist", "available tables", "existing tables",
            "show tables", "show table", "what tables", "which tables",
            "tables available", "tables do we have", "tables are there",
            "all the columns", "list columns", "list column", "show columns",
            "show column", "what columns", "which columns", "all columns",
            "column names", "column name",
            "list schemas", "list schema", "all schemas", "database schema", "schema list",
            "database size", "database version",
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
        if self.mongodb_service:
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
        """Get query result by index from history.

        self.query_history is only populated within the lifetime of a single request
        (a fresh QueryService is constructed per-request), so it's empty for any request
        that didn't itself just run process_query/stream_query. Fall back to the same
        persisted history get_history() reads, so sharing by index matches what the
        history endpoint actually displays.
        """
        history = self.query_history or self.get_history(limit=1000)
        if index < 0 or index >= len(history):
            raise ValueError(f"Invalid index {index}. History has {len(history)} items.")
        return history[index]
    
    def get_latest_result(self) -> Dict[str, Any]:
        """Get the latest query result"""
        if not self.query_history:
            raise ValueError("No query results in history")
        return self.query_history[-1]