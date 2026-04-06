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
        
    def process_query(self, user_query: str, max_tokens: int = 1024, temperature: float = 0.0, 
                      user_id: str = None, session_id: str = None, message_id: str = None, company_id: str = None) -> Dict[str, Any]:
        """Process natural language query and return results (Enhanced 2-step approach)"""
        start_time = time.time()
        
        try:
            # Validate prerequisites first
            self.validate_prerequisites()
            
            print(f"Processing query: {user_query[:100]}...")
            
            # 1. FETCH RELEVANT TABLES FROM NEO4J (LLM CALL 1)
            db_params = self.db_service.get_connection_params()
            host = db_params.get("host", "unknown")
            db_name = db_params.get("database", "unknown")
            
            print(f"[STEP 1] Using Neo4j graph for schema discovery in DB: '{db_name}'...")
            
            # Token tracking
            input_tokens = self.count_tokens(user_query)
            output_tokens = 0
            
            schema_context = ""
            try:
                # Use Neo4j if available, otherwise fallback to MongoDB or full schema
                if self.neo4j_service and self.neo4j_service.is_connected():
                    print("[STEP 1] Extracting keywords for Neo4j search...")
                    keyword_chain = self.llm_service.create_keyword_extraction_chain()
                    keywords_text = keyword_chain.invoke({"Question": user_query})
                    output_tokens += self.count_tokens(str(keywords_text))
                    
                    keywords = [k.strip() for k in keywords_text.split(",") if k.strip()]
                    print(f"[STEP 1] Extracted keywords: {keywords}")
                    
                    relevant_nodes = self.neo4j_service.find_relevant_schema(db_name, keywords)
                    # Limit to 15 relevant tables to prevent overly large context
                    relevant_nodes = relevant_nodes[:15]
                    print(f"[STEP 1] Found {len(relevant_nodes)} relevant tables in Neo4j.")
                    
                    if relevant_nodes:
                        schema_context = f"Relevant Tables for database '{db_name}' (discovered via Neo4j graph):\n"
                        for node in relevant_nodes:
                            cols_desc = ", ".join([f"{c['name']} ({c['type']})" for c in node.get("columns", [])])
                            schema_context += f"- Table: {node['table_name']} (Columns: {cols_desc})\n"
                    else:
                        print("[STEP 1] No relevant nodes found in Neo4j. Checking MongoDB fallback...")
                
                # Fallback to MongoDB if Neo4j failed or returned nothing
                if not schema_context and self.mongodb_service:
                    print(f"[STEP 1] Falling back to MongoDB for DB: '{db_name}'...")
                    search_chain = self.llm_service.create_table_search_mongodb_chain()
                    mongo_filter_text = search_chain.invoke({"Question": user_query})
                    
                    clean_filter = mongo_filter_text.strip()
                    if clean_filter.startswith("```"):
                       if "json" in clean_filter:
                           clean_filter = clean_filter.split("json", 1)[1].rsplit("```", 1)[0].strip()
                       else:
                           clean_filter = clean_filter.split("```", 1)[1].rsplit("```", 1)[0].strip()
                    
                    filter_json = json.loads(clean_filter)
                    relevant_table_docs = self.mongodb_service.query_table_metadata(host, db_name, filter_json)
                    
                    if relevant_table_docs:
                        schema_context = f"Relevant Tables for database '{db_name}' (discovered via MongoDB):\n"
                        for doc in relevant_table_docs[:15]:
                            cols_desc = ", ".join([f"{c['name']} ({c['type']})" for c in doc.get("columns", [])])
                            schema_context += f"- Table: {doc['table']} (Columns: {cols_desc})\n"

                # Final fallback to simplified full schema
                if not schema_context:
                    print("[STEP 1] No discovery possible. Using full simplified schema.")
                    schema_context = self.db_service.get_simplified_schema()
            
            except Exception as discovery_err:
                print(f"[ERROR] Schema discovery failed: {discovery_err}. Falling back to full schema.")
                schema_context = self.db_service.get_simplified_schema()
            
            # Final safety truncation (max approx 8000 tokens)
            if len(schema_context) > 24000:
                print(f"[STEP 1] Truncating schema context from {len(schema_context)} characters...")
                schema_context = schema_context[:24000] + "\n[...schema truncated for size...]"

            # 2. GENERATE SQL (LLM CALL 2)
            print(f"[STEP 2] Generating PostgreSQL SQL for DB: '{db_name}'...")
            sql_gen_chain = self.llm_service.create_sql_generation_chain()
            
            # Update tokens for Step 2
            input_tokens += self.count_tokens(user_query) + self.count_tokens(schema_context)
            
            try:
                generated_text = sql_gen_chain.invoke({
                    "Question": user_query,
                    "schema_context": schema_context
                })
                print(f"[STEP 2] Successfully generated SQL for '{db_name}'.")
            except Exception as sql_err:
                print(f"[ERROR] SQL generation failed for '{db_name}': {sql_err}")
                raise RuntimeError(f"Step 2 SQL generation failed: {sql_err}")
            
            # Count output tokens for SQL generation
            output_tokens += self.count_tokens(str(generated_text))
            
            # Extract SQL queries
            sql_queries = extract_sql_queries(str(generated_text))
            
            if not sql_queries:
                raise ValueError(f"No SQL queries generated for '{db_name}' from the LLM response.")
            
            print(f"✓ Extracted {len(sql_queries)} SQL queries")
            
            # Execute queries and collect results
            results = []
            for i, query in enumerate(sql_queries):
                print(f"Executing query {i+1}: {query[:100]}...")
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
            
            print("✓ Executed all queries")
            
            # Generate natural language explanation
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
            
            print("✓ Generated explanation")
            
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
                    print(f"[INFO] Result saved to MongoDB with ID: {mongo_id}")
                except Exception as e:
                    print(f"[ERROR] Failed to save to MongoDB: {e}")
            
            print(f"[INFO] Query processed successfully in {execution_time:.2f}s | Tokens: In={input_tokens}, Out={output_tokens}")
            return response
            
        except Exception as e:
            print(f"✗ Query processing failed: {str(e)}")
            raise RuntimeError(f"Query processing failed: {str(e)}")
    
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