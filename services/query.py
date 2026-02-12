from typing import List, Dict, Any, Tuple
import time
from datetime import datetime

from services.database import DatabaseService
from services.llm import LLMService
from services.billing.billing_service import BillingService
from utils.parsing import extract_sql_queries
import tiktoken

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
        
    def process_query(self, user_query: str, max_tokens: int = 1024, temperature: float = 0.0, user_id: str = None, session_id: str = None) -> Dict[str, Any]:
        """Process natural language query and return results"""
        start_time = time.time()
        
        try:
            # Validate prerequisites first
            self.validate_prerequisites()
            
            print(f"Processing query: {user_query[:100]}...")
            
            # Get database and LLM instances
            db = self.db_service.get_langchain_db()
            llm = self.llm_service.get_llm()
            
            print("✓ Got database and LLM instances")
            
            # Get simplified schema info (avoids SQL DDL to reduce WAF triggers)
            table_info = self.db_service.get_simplified_schema()
            print(f"✓ Got simplified schema: {len(table_info)} characters")
            
            # Generate SQL query
            sql_chain = self.llm_service.create_sql_chain(db)
            print("✓ Created SQL chain")
            
            # Prepare input data for SQL generation
            sql_input = {
                "Question": user_query,
                "schema_info": table_info,
                "table_info": table_info
            }
            
            # Count input tokens for SQL generation (approximate by counting variables)
            # For more accuracy, we would count the full formatted prompt
            input_tokens = self.count_tokens(user_query) + self.count_tokens(table_info) * 2
            
            generated_text = sql_chain.invoke(sql_input)
            print(f"✓ Generated text: {generated_text[:200]}...")
            
            # Count output tokens for SQL generation
            output_tokens = self.count_tokens(str(generated_text))
            
            # Extract SQL queries
            sql_queries = extract_sql_queries(str(generated_text))
            
            if not sql_queries:
                raise ValueError(f"No SQL queries generated from the LLM response: {generated_text}")
            
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
                "schema_info": table_info,
                "results": str(results)
            }
            
            # Add to input tokens for explanation
            input_tokens += self.count_tokens(user_query) + self.count_tokens(table_info)
            
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
                "session_id": session_id
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