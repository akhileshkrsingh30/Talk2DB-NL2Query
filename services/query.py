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
            
            # STEP 1: COMPACT SCHEMA RETRIEVAL (DIRECT FROM DB)
            try:
                logging.info(f"[STEP 1] Fetching compact schema for '{db_name}'...")
                
                # Simple retrieval directly from the DB metadata
                schema_context = self.db_service.get_simplified_schema()
                
                # Additional truncation for speed if needed
                if len(schema_context) > 30000:
                    schema_context = schema_context[:30000] + "\n[...schema truncated for speed...]"
                
                logging.info(f"[STEP 1] Compact schema ready ({len(schema_context)} chars).")
                
                # Final fallback to simplified full schema if discovery somehow returned empty
                if not schema_context:
                    if is_meta_query:
                        logging.info("[STEP 1] Injecting metadata schema context (information_schema)...")
                        schema_context = self._get_meta_context(db_name)
                    else:
                        logging.info("[STEP 1] No discovery possible. Using full simplified schema.")
                        schema_context = self.db_service.get_simplified_schema()
            
            except Exception as discovery_err:
                err_str = str(discovery_err)
                logging.error(f"[ERROR] Schema discovery failed: {err_str}. Falling back to full schema.")
                schema_context = self.db_service.get_simplified_schema()
            
            # Final safety truncation (based on configured context window)
            if len(schema_context) > settings.llm_max_context_chars:
                logging.info(f"[STEP 1] Truncating schema context from {len(schema_context)} characters to {settings.llm_max_context_chars}...")
                schema_context = schema_context[:settings.llm_max_context_chars] + "\n[...schema truncated for size...]"
            logging.info(f"--- FINAL SCHEMA CONTEXT SENT TO LLM ---\n{schema_context}\n----------------------------------------")
            
            # 2. GENERATE SQL (LLM CALL 1 - COMBINED)
            logging.info(f"[STEP 2] Generating SQL directly...")
            sql_gen_chain = self.llm_service.create_sql_generation_chain()
            
            input_tokens = self.count_tokens(user_query) + self.count_tokens(schema_context)
            
            generated_text = sql_gen_chain.invoke({
                "Question": user_query,
                "schema_context": schema_context
            })
            output_tokens = self.count_tokens(str(generated_text))
            sql_queries = extract_sql_queries(str(generated_text))
            
            # No secondary fallback if first one has context

            
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
            
            # 5. PERSISTENCE (Save to MongoDB for history and sharing)
            if self.mongodb_service:
                try:
                    mongo_id = self.mongodb_service.save_result(response)
                    if mongo_id:
                        response["mongodb_id"] = mongo_id
                        logging.info(f"[OK] Response result saved to MongoDB (ID: {mongo_id})")
                except Exception as mongo_err:
                    logging.error(f"[ERROR] Failed to save result to MongoDB: {mongo_err}")

            
            logging.info(f"[INFO] Query processed successfully in {execution_time:.2f}s | Tokens: In={input_tokens}, Out={output_tokens}")
            return response
            
        except Exception as e:
            print(f"[FAIL] Query processing failed: {str(e)}")
            raise RuntimeError(f"Query processing failed: {str(e)}")
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