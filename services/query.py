from typing import List, Dict, Any, Tuple
import time
from datetime import datetime

from services.database import DatabaseService
from services.llm import LLMService
from services.billing.billing_service import BillingService
from services.neo4j_service import Neo4jService
from utils.parsing import extract_sql_queries
import tiktoken
import json
import logging
from config import settings

class QueryService:
    def __init__(self, db_service: DatabaseService, llm_service: LLMService, billing_service: BillingService = None, mongodb_service = None, neo4j_service = None):
        self.db_service = db_service
        self.llm_service = llm_service
        self.billing_service = billing_service
        self.mongodb_service = mongodb_service
        self.neo4j_service = neo4j_service
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
                      user_id: str = None, session_id: str = None, message_id: str = None, company_id: str = None) -> Dict[str, Any]:
        """Process natural language query and return results (Enhanced 2-step approach)"""
        start_time = time.time()
        
        try:
            # Validate prerequisites first
            self.validate_prerequisites()
            
            logging.info(f"--- START PROCESSING QUERY: '{user_query[:50]}...' ---")
            
            # Detect if this is a meta-query about the database structure itself
            is_meta_query = self._detect_meta_query(user_query)
            
            # 1. FETCH RELEVANT TABLES FROM NEO4J (LLM CALL 1)
            db_params = self.db_service.get_connection_params()
            host = db_params.get("host", "unknown")
            db_name = db_params.get("database", "unknown")
            
            logging.info(f"[STEP 1] Using Neo4j graph for schema discovery in DB: '{db_name}'...")
            
            # Token tracking
            input_tokens = self.count_tokens(user_query)
            output_tokens = 0
            
            schema_context = ""
            try:
                if self.neo4j_service and self.neo4j_service.is_connected():
                    logging.info("[STEP 1] Starting Iterative Graph-Based Discovery...")
                    
                    # 1A. Concept Extraction
                    concept_chain = self.llm_service.create_concept_extraction_chain()
                    keywords_text = concept_chain.invoke({"Question": user_query})
                    output_tokens += self.count_tokens(str(keywords_text))
                    keywords = [k.strip() for k in keywords_text.split(",") if k.strip()]
                    logging.info(f"[STEP 1] Extracted business concepts: {keywords}")
                    
                    # 1B. Anchor Retrieval (Initial Ranking)
                    anchors = self.neo4j_service.find_relevant_schema(db_name, keywords)
                    logging.info(f"[STEP 1] Found {len(anchors)} anchor candidates in Neo4j.")
                    
                    if anchors:
                        # 1C. Join Path Expansion (Path Finding between anchors)
                        anchor_full_names = [a['full_name'] for a in anchors[:8]] # Use top 8 for path finding
                        bridges = self.neo4j_service.get_path_bridges(db_name, anchor_full_names)
                        logging.info(f"[STEP 1] Discovered {len(bridges)} bridging tables via FK paths.")
                        
                        all_relevant_nodes = anchors + bridges
                        
                        # 1D. Target Check & Iteration (Planning Step)
                        # We use capsules for the planner to keep context small
                        candidate_context = self._format_schema_capsules(all_relevant_nodes[:30], db_name)
                        
                        planner_chain = self.llm_service.create_schema_planner_chain()
                        plan_resp = planner_chain.invoke({
                            "Question": user_query,
                            "schema_context": candidate_context
                        })
                        
                        try:
                            plan = json.loads(plan_resp)
                            if plan.get("status") == "need_more_schema":
                                logging.info(f"[STEP 1] Planner detected missing concepts: {plan['missing_concepts']}. Expanding...")
                                extra_terms = plan.get("next_search_terms", [])
                                extra_nodes = self.neo4j_service.find_relevant_schema(db_name, extra_terms)
                                all_relevant_nodes.extend(extra_nodes)
                        except:
                            logging.warning("[STEP 1] Planner returned invalid JSON. Proceeding with current nodes.")
                        
                        # Formatting Final Capsules
                        schema_context = self._format_schema_capsules(all_relevant_nodes[:40], db_name)
                        logging.info(f"[STEP 1] Final iterative discovery yielded {len(all_relevant_nodes)} tables.")
                    else:
                        logging.info("[STEP 1] Neo4j search returned 0 matches for keywords.")
                else:
                    logging.warning("⚠️ [STEP 1] Neo4j service is NOT connected. Skipping graph search.")
                
                # Fallback to PostgreSQL if Neo4j discovery yielded no results
                if not schema_context:
                    logging.warning("⚠️ [STEP 1] Neo4j returned no schema context. Falling back to PostgreSQL simplified schema...")
                    schema_context = self.db_service.get_simplified_schema()
                    if schema_context:
                        logging.info("[STEP 1] Successfully retrieved simplified schema from PostgreSQL.")
                    else:
                        logging.error("[STEP 1] PostgreSQL simplified schema is also empty.")
            
            except Exception as discovery_err:
                err_str = str(discovery_err)
                if "404" in err_str and ("not found" in err_str.lower() or "model" in err_str.lower()):
                    c = self.llm_service.config_details
                    if c and c.get("model") != settings.llm_model_name:
                        logging.warning(f"⚠️ Auto-reverting model to default '{settings.llm_model_name}' due to 404.")
                        self.llm_service.configure(c.get("api_key"), c.get("base_url"), settings.llm_model_name, c.get("headers"), False)
                        raise RuntimeError(f"Self-healed LLM Config to '{settings.llm_model_name}'. Please re-run your query.")

                if any(x in err_str for x in ["Connection error", "Connection refused", "unreachable", "10061"]):
                    logging.warning(f"⚠️ [STEP 1] LLM Service unreachable during discovery: {err_str}. Discovery skipped.")
                else:
                    logging.error(f"[ERROR] Schema discovery failed: {err_str}.")
                
                # Fallback to PostgreSQL simplified schema on any discovery error
                logging.warning("⚠️ [STEP 1] Falling back to PostgreSQL simplified schema due to discovery error...")
                try:
                    schema_context = self.db_service.get_simplified_schema()
                except Exception as pg_err:
                    logging.error(f"[ERROR] PostgreSQL fallback also failed: {pg_err}")
            
            # Final safety truncation (based on configured context window)
            if len(schema_context) > settings.llm_max_context_chars:
                logging.info(f"[STEP 1] Truncating schema context from {len(schema_context)} characters to {settings.llm_max_context_chars}...")
                schema_context = schema_context[:settings.llm_max_context_chars] + "\n[...schema truncated for size...]"
            logging.info(f"--- FINAL SCHEMA CONTEXT SENT TO LLM ---\n{schema_context}\n----------------------------------------")
            
            # 2. GENERATE SQL (LLM CALL 2)
            dialect = self.db_service.db_type
            logging.info(f"[STEP 2] Generating {dialect.upper()} SQL for DB: '{db_name}'...")
            sql_gen_chain = self.llm_service.create_sql_generation_chain(dialect=dialect)
            
            # Update tokens for Step 2
            input_tokens += self.count_tokens(user_query) + self.count_tokens(schema_context)
            
            try:
                generated_text = sql_gen_chain.invoke({
                    "Question": user_query,
                    "schema_context": schema_context
                })
                logging.info(f"[STEP 2] Successfully generated AI SQL for '{db_name}'.")
            except Exception as sql_err:
                err_str = str(sql_err)
                logging.error(f"[ERROR] SQL generation failed: {err_str}")
                configured_model = self.llm_service.config_details.get("model", "unknown") if self.llm_service.config_details else "unknown"
                llm_base = self.llm_service.config_details.get("base_url", "the configured LLM server") if self.llm_service.config_details else "the configured LLM server"
                # Detect LLM server unreachable
                if any(x in err_str for x in ["Connection error", "Connection refused", "10061", "NewConnectionError"]):
                    raise RuntimeError(
                        f"LLM server is unreachable at '{llm_base}'. "
                        f"Check if the service is running or if there's a network/proxy issue."
                    )
                # Detect model not found (404)
                if "404" in err_str and ("not found" in err_str.lower() or "model" in err_str.lower()):
                    c = self.llm_service.config_details
                    if c and c.get("model") != settings.llm_model_name:
                        logging.warning(f"⚠️ Auto-reverting model to default '{settings.llm_model_name}' due to 404.")
                        self.llm_service.configure(c.get("api_key"), c.get("base_url"), settings.llm_model_name, c.get("headers"), False)
                        raise RuntimeError(f"Self-healed LLM Config to '{settings.llm_model_name}'. Please re-run your query.")
                    raise RuntimeError(
                        f"Model '{configured_model}' not found on '{llm_base}'. "
                        f"Please re-configure with a valid model name."
                    )
                raise RuntimeError(f"SQL Generation failed: {err_str}")
            
            # Count output tokens for SQL generation
            output_tokens += self.count_tokens(str(generated_text))
            
            # Extract SQL queries
            sql_queries = extract_sql_queries(str(generated_text))
            
            # Removed insufficient schema fallback to PostgreSQL.
            # If the LLM generates 'Insufficient schema context', it will be executed and return a message to the user.
            
            if not sql_queries:
                raise ValueError(f"No SQL queries generated for '{db_name}' from the LLM response.")
            
            print(f"[OK] Extracted {len(sql_queries)} SQL queries")
            
            logging.info(f"[STEP 3] Executing {len(sql_queries)} queries against '{db_name}'...")
            
            # Execute queries and collect results
            results = []
            for i, query in enumerate(sql_queries):
                logging.info(f"   -> EXECUTING Q{i+1}: {query[:80]}...")
                query_result = self.db_service.execute_query(query)
                
                # Ensure the result is properly formatted
                if isinstance(query_result, list):
                    # Already converted to list of dicts in database service
                    formatted_result = query_result
                elif isinstance(query_result, dict):
                    # Command result (INSERT, UPDATE, DELETE, etc.)
                    formatted_result = query_result
                else:
                    # Fallback for unexpected types
                    formatted_result = {"raw_result": str(query_result)}
                
                results.append(formatted_result)
            
            logging.info("[OK] [STEP 3] Successfully executed all queries.")
            
            # 4. EXPLAIN RESULTS (LLM CALL 3)
            logging.info("[STEP 4] Generating natural language explanation...")
            explanation_chain = self.llm_service.create_explanation_chain()
            
            # Prepare input data for explanation
            explanation_input = {
                "Question": user_query,
                "schema_info": schema_context,
                "results": str(results)
            }
            
            # Add to input tokens for explanation
            input_tokens += self.count_tokens(user_query) + self.count_tokens(schema_context)
            
            explanation = explanation_chain.invoke(explanation_input)
            
            # Add to output tokens for explanation
            output_tokens += self.count_tokens(str(explanation))
            
            logging.info("--- FINISHED PROCESSING QUERY ---")
            
            # Calculate execution time
            execution_time = time.time() - start_time
            
            # Calculate billing if service is available
            billing_info = None
            if self.billing_service:
                billing_info = self.billing_service.calculate_cost(input_tokens, output_tokens, user_id, session_id)
            
            # Prepare response
            response = {
                "query": user_query,
                "sql_queries": [{"sql": sql_queries[i], "order": i} for i in range(len(sql_queries))],
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
                "company_id": company_id
            }
            
            # Store in history
            self.query_history.append(response)
            
            # Persist to MongoDB if available
            if self.mongodb_service:
                try:
                    mongo_id = self.mongodb_service.save_result(response)
                    response["mongodb_id"] = mongo_id
                    logging.info(f"[INFO] Result saved to MongoDB with ID: {mongo_id}")
                except Exception as e:
                    logging.error(f"[ERROR] Failed to save to MongoDB: {e}")
            
            logging.info(f"[INFO] Query processed successfully in {execution_time:.2f}s | Tokens: In={input_tokens}, Out={output_tokens}")
            return response

        except Exception as e:
            logging.error(f"[ERROR] process_query failed: {e}")
            raise
            
    async def stream_query(self, user_query: str, max_tokens: int = 4096, temperature: float = 0.0, 
                          user_id: str = None, session_id: str = None, message_id: str = None, company_id: str = None):
        """Process natural language query and stream results chunk by chunk"""
        start_time = time.time()
        input_tokens = self.count_tokens(user_query)
        output_tokens = 0
        
        try:
            # 1. Validation & Initialization
            self.validate_prerequisites()
            yield json.dumps({"type": "status", "content": "Analyzing query and discovering schema..."}) + "\n"
            
            db_params = self.db_service.get_connection_params()
            db_name = db_params.get("database", "unknown")
            
            # 2. Schema Discovery (Step 1)
            schema_context = ""
            if self.neo4j_service and self.neo4j_service.is_connected():
                try:
                    concept_chain = self.llm_service.create_concept_extraction_chain()
                    keywords_text = await concept_chain.ainvoke({"Question": user_query})
                    keywords = [k.strip() for k in keywords_text.split(",") if k.strip()]
                    
                    anchors = self.neo4j_service.find_relevant_schema(db_name, keywords)
                    if anchors:
                        anchor_full_names = [a['full_name'] for a in anchors[:8]]
                        bridges = self.neo4j_service.get_path_bridges(db_name, anchor_full_names)
                        all_relevant_nodes = anchors + bridges
                        schema_context = self._format_schema_capsules(all_relevant_nodes[:40], db_name)
                except Exception as e:
                    logging.warning(f"Neo4j discovery failed during stream: {e}")

            # Fallback to Postgres if Neo4j failed or returned nothing
            if not schema_context:
                yield json.dumps({"type": "status", "content": "Neo4j unavailable, falling back to PostgreSQL schema..."}) + "\n"
                schema_context = self.db_service.get_simplified_schema()

            # 3. SQL Generation (Step 2)
            dialect = self.db_service.db_type
            yield json.dumps({"type": "status", "content": f"Generating {dialect.upper()} query..."}) + "\n"
            sql_gen_chain = self.llm_service.create_sql_generation_chain(dialect=dialect)
            generated_text = await sql_gen_chain.ainvoke({
                "Question": user_query,
                "schema_context": schema_context
            })
            
            sql_queries = extract_sql_queries(str(generated_text))
            if not sql_queries:
                yield json.dumps({"type": "error", "content": "No SQL queries generated."}) + "\n"
                return

            yield json.dumps({"type": "sql", "content": sql_queries}) + "\n"

            # 4. SQL Execution (Step 3)
            yield json.dumps({"type": "status", "content": "Executing SQL and retrieving data..."}) + "\n"
            results = []
            for query in sql_queries:
                query_result = self.db_service.execute_query(query)
                results.append(query_result)
            
            yield json.dumps({"type": "results", "content": results}) + "\n"

            # 5. Explaining Results (Step 4 - The actual Stream)
            yield json.dumps({"type": "status", "content": "Generating explanation..."}) + "\n"
            explanation_chain = self.llm_service.create_explanation_chain()
            
            explanation_input = {
                "Question": user_query,
                "schema_info": schema_context,
                "results": str(results)
            }
            
            yield json.dumps({"type": "explanation_start"}) + "\n"
            full_explanation = ""
            async for chunk in explanation_chain.astream(explanation_input):
                full_explanation += chunk
                yield json.dumps({"type": "explanation_chunk", "content": chunk}) + "\n"
            
            # Final metadata
            execution_time = time.time() - start_time
            yield json.dumps({
                "type": "metadata", 
                "execution_time": execution_time,
                "timestamp": datetime.now().isoformat()
            }) + "\n"

        except Exception as e:
            logging.error(f"Streaming query failed: {e}")
            yield json.dumps({"type": "error", "content": str(e)}) + "\n"

    def _detect_meta_query(self, query: str) -> bool:
        """Detect if the query is asking about the database structure itself (metadata)."""
        meta_keywords = [
            "number of tables", "how many tables", "list schemas", 
            "database size", "database version", "all tables",
            "metadata", "structure", "schema list"
        ]
        q_lower = query.lower()
        return any(kw in q_lower for kw in meta_keywords)

    def _get_meta_context(self, db_name: str) -> str:
        """Provide context for metadata queries (information_schema)."""
        return f"""
        This is a metadata query for the database '{db_name}'. 
        You may use PostgreSQL system tables like:
        - information_schema.tables (table_name, table_schema)
        - information_schema.columns (table_name, column_name, data_type)
        - pg_stat_user_tables (relname, n_live_tup as row_count)
        
        To count tables, use: SELECT count(*) FROM information_schema.tables WHERE table_schema NOT IN ('information_schema', 'pg_catalog');
        """
    
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

    def get_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get query history. Falls back to MongoDB if available for persistent history."""
        # Try to get from MongoDB for persistent history
        if self.mongodb_service:
            try:
                mongo_history = self.mongodb_service.get_history(limit)
                if mongo_history:
                    return mongo_history
            except Exception as e:
                print(f"[ERROR] Failed to fetch history from MongoDB: {e}")
        
        # Fallback to in-memory history
        return self.query_history[-limit:] if self.query_history else []
    
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