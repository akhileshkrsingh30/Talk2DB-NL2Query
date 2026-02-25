from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from typing import Optional, Dict, Any
import requests

from config import settings

class LLMService:
    def __init__(self):
        self.llm = None
        self.configured = False
        self.config_details: Optional[Dict[str, Any]] = None
        self.last_error: Optional[str] = None
        
    def test_api_key(self, api_key: str, base_url: str, model: str = "gpt-3.5-turbo", headers: Optional[Dict[str, str]] = None) -> bool:
        """Test if the API key is valid by making a simple request"""
        try:
            self.last_error = None
            # Test with a simple request to validate the API key
            base_headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            if headers:
                base_headers.update(headers)
            
            # Simple test payload
            test_payload = {
                "model": model,
                "messages": [{"role": "user", "content": "Hello"}],
                "max_completion_tokens": 10
            }
            
            response = requests.post(
                f"{base_url}/chat/completions",
                headers=base_headers,
                json=test_payload,
                timeout=10
            )
            
            if response.status_code == 200:
                print("API Key validation successful")
                return True
            elif response.status_code == 401:
                self.last_error = "Unauthorized (401): Invalid API key"
                print(f"API Key validation failed: {self.last_error}")
                return False
            else:
                # Capture a short preview of the body to avoid huge logs
                body_preview = response.text[:300].replace("\n", " ")
                self.last_error = f"HTTP {response.status_code}: {body_preview}"
                print(f"API Key validation failed: {self.last_error}")
                return False
                
        except Exception as e:
            self.last_error = f"Exception during API key test: {e}"
            print(f"API Key test failed with exception: {e}")
            return False  # Conservative approach
        
    def configure(self, api_key: str, base_url: str = None, model: str = None, headers: Optional[Dict[str, str]] = None, validate_key: bool = True) -> bool:
        """Configure LLM service"""
        try:
            if not api_key or api_key.strip() == "":
                raise ValueError("API key is required and cannot be empty")
            
            # Clean up the inputs
            api_key = api_key.strip()
            base_url = (base_url or settings.openai_api_base).strip()
            
            # Default to OpenAI official API if base_url is empty
            if not base_url:
                base_url = "https://api.openai.com/v1"
                
            model = (model or settings.llm_model_name).strip()
            
            print(f"Configuring LLM with:")
            print(f"   API Base: {base_url}")
            print(f"   Model: {model}")
            print(f"   API Key: {api_key[:10]}...")
            if headers:
                print(f"   Custom headers: {list(headers.keys())}")
            
            # Test the API key first (unless bypassed)
            if validate_key and not self.test_api_key(api_key, base_url, model, headers):
                raise ValueError(self.last_error or "Invalid API key or connection failed. Please check your credentials and network access.")
            
            # Store configuration details
            self.config_details = {
                "api_key": api_key[:10] + "..." if len(api_key) > 10 else api_key,
                "base_url": base_url,
                "model": model,
                "headers": list(headers.keys()) if headers else None
            }
            
            # Create the LLM instance
            self.llm = ChatOpenAI(
                openai_api_base=base_url,
                openai_api_key=api_key,
                model=model,
                temperature=0.0,
                model_kwargs={"max_completion_tokens": 1024},
                default_headers=headers,
            )
            
            self.configured = True
            print(f"LLM configured successfully with model: {model}")
            return True
            
        except Exception as e:
            self.configured = False
            self.llm = None
            self.config_details = None
            print(f"LLM configuration failed: {str(e)}")
            raise RuntimeError(f"LLM configuration failed: {str(e)}")
    
    def _attempt_auto_configure(self):
        """Attempt to auto-configure using environment variables if not already configured"""
        if self.configured and self.llm is not None:
            return

        import os
        from config import settings
        
        # Priority: Settings -> os.environ
        api_key = settings.krutim_cloud_api_key or settings.openai_api_key or os.getenv("OPENAI_API_KEY") or os.getenv("KRUTIM_CLOUD_API_KEY")
        
        if api_key and api_key.strip():
            try:
                print(f"Lazy-configuring LLM from environment...")
                self.configure(
                    api_key=api_key,
                    base_url=settings.openai_api_base or os.getenv("OPENAI_API_BASE"),
                    model=settings.llm_model_name or os.getenv("LLM_MODEL_NAME") or "gpt-5.2",
                    validate_key=False
                )
            except Exception as e:
                print(f"Lazy-configuration failed: {e}")

    def is_configured(self) -> bool:
        """Check if LLM is configured (with lazy-load attempt)"""
        if not self.configured or self.llm is None:
            self._attempt_auto_configure()
        return self.configured and self.llm is not None
    
    def get_llm(self):
        """Get LLM instance (with lazy-load attempt)"""
        if not self.is_configured():
            # is_configured calls _attempt_auto_configure
            raise RuntimeError("LLM not configured. Please configure the LLM using /llm/configure endpoint first.")
        return self.llm
    
    def get_config_details(self) -> Optional[Dict[str, Any]]:
        """Get configuration details (without sensitive data)"""
        return self.config_details
    
    def reset_configuration(self):
        """Reset LLM configuration"""
        self.llm = None
        self.configured = False
        self.config_details = None
        print("LLM configuration reset")
    
    def create_sql_chain(self, db):
        """Create SQL query chain"""
        if not self.is_configured():
            raise RuntimeError("LLM not configured. Cannot create SQL chain.")
            
        prompt = ChatPromptTemplate.from_template(
            """You are a PostgreSQL expert. Generate syntactically correct SQL for the following question.
            Return only SQL. Use this database schema:
            {schema_info}

            Question: {Question}

            CRITICAL RULES:
            - Use ONLY the exact column names provided in the schema above
            - Do NOT use generic column names like "date"; verify the exact column name from the schema
            - Double-check that every referenced column exists in the schema
            - Use proper PostgreSQL syntax
            - For date/timestamp columns, verify the exact column name from the schema (e.g., order_date, created_at)
            - Return only the SQL query, no explanations or markdown
            """
        )
        return prompt | self.llm | StrOutputParser()
    
    def create_explanation_chain(self):
        """Create natural language explanation chain"""
        if not self.is_configured():
            raise RuntimeError("LLM not configured. Cannot create explanation chain.")
            
        return ChatPromptTemplate.from_template(
            """You are a helpful data assistant. Given a user's question, the database schema, and the results of a SQL query, provide a clear and concise natural language explanation of the results.

            User's Question: {Question}
            Database Schema: {schema_info}
            Query Results: {results}

            Instructions:
            1. Provide a direct, professional, and conversational answer to the user's question.
            2. CRITICAL: Do NOT use any Markdown formatting. No asterisks (**), no hashtags (#), no backticks (`), and no bolding symbols.
            3. Use standard sentence case and normal punctuation.
            4. If the data results are empty, state clearly that no records were found.
            5. Present any lists using simple numbers (1., 2.) or bullet points (- ) that are readable as plain text.
            6. The summary should be easy to read in any plain text application.
            """
        ) | self.llm | StrOutputParser()

    def create_table_search_mongodb_chain(self):
        """Step 1: Generate a MongoDB query to find relevant tables from metadata"""
        if not self.is_configured():
            raise RuntimeError("LLM not configured.")

        prompt = ChatPromptTemplate.from_template(
            """You are a database expert. Your task is to generate a MongoDB find() query to search for relevant tables in a PostgreSQL schema metadata collection.
            
            Metadata Collection Schema (collection: table_metadata):
            - table: table name
            - schema: schema name (usually 'public')
            - database: database name
            - host: host name
            - column_names: array of strings (e.g., ["id", "name", "created_at"])
            
            User's Question: {Question}
            
            Instructions:
            - Return ONLY a valid JSON object used as the filter for MongoDB find().
            - The filter should use $or and $regex to search in both "table" and "column_names".
            - Make the regex case-insensitive using $options: "i".
            - Only return the raw JSON object.
            
            Example Output:
            {{"$or": [{{"table": {{"$regex": "user", "$options": "i"}}}}, {{"column_names": {{"$regex": "email", "$options": "i"}}}}]}}
            """
        )
        return prompt | self.llm | StrOutputParser()

    def create_sql_generation_chain(self):
        """Step 2: Generate final SQL from filtered schema context"""
        if not self.is_configured():
            raise RuntimeError("LLM not configured.")

        prompt = ChatPromptTemplate.from_template(
            """You are a PostgreSQL expert. Generate syntactically correct SQL for the following question.
            Use ONLY the tables and columns provided in the schema context below.
            
            Schema Context:
            {schema_context}
            
            User's Question: {Question}
            
            CRITICAL RULES:
            - Use ONLY the provided tables and columns.
            - Ensure correct JOIN conditions.
            - Use proper PostgreSQL syntax.
            - Return only the SQL query, no markdown, no explanation.
            """
        )
        return prompt | self.llm | StrOutputParser()

    def create_mongodb_chain(self):
        """Create MongoDB query chain - generates MongoDB find queries from natural language"""
        if not self.is_configured():
            raise RuntimeError("LLM not configured. Cannot create MongoDB chain.")
            
        prompt = ChatPromptTemplate.from_template(
            """You are a MongoDB expert. Generate a valid MongoDB query for the following question.
            The query will be used with PyMongo's find() method.

            Collection Schema (sample document fields):
            {schema_info}

            Question: {Question}

            CRITICAL RULES:
            - Return ONLY a valid JSON object with two keys: "filter" and "projection"
            - "filter" is the MongoDB query filter (the first argument to find())
            - "projection" is the fields to return (the second argument to find()). Use 1 to include, 0 to exclude. Always exclude "_id" unless specifically asked.
            - Use ONLY the exact field names from the schema above
            - For geospatial queries, use native MongoDB operators like $near, $nearSphere, $geoWithin, or $geoIntersects if the schema contains 2dsphere indexes or coordinates. 
            - If calculating distance manually via $expr, keep the formula as concise as possible to avoid truncation.
            - For string matching, use $regex with $options: "i" for case-insensitive
            - For numeric comparisons use $gt, $gte, $lt, $lte, $eq, $ne
            - For sorting, add a "sort" key with field and direction (1=asc, -1=desc)
            - For limiting results, add a "limit" key with an integer value
            - Do NOT wrap the JSON in markdown code blocks or backticks
            - Return ONLY the raw JSON object, nothing else
            - ENSURE the JSON is complete and valid.

            Example output:
            {{"filter": {{"age": {{"$gt": 25}}}}, "projection": {{"name": 1, "age": 1, "_id": 0}}, "sort": {{"age": -1}}, "limit": 10}}
            """
        )
        return prompt | self.llm | StrOutputParser()

    def create_mongodb_explanation_chain(self):
        """Create natural language explanation chain for MongoDB results"""
        if not self.is_configured():
            raise RuntimeError("LLM not configured. Cannot create MongoDB explanation chain.")
            
        return ChatPromptTemplate.from_template(
            """You are a helpful data assistant. Given a user's question, the collection schema, and the results of a MongoDB query, provide a clear and concise natural language explanation of the results.

            User's Question: {Question}
            Collection Schema: {schema_info}
            Query Results: {results}

            Instructions:
            1. Provide a direct, professional, and conversational answer to the user's question.
            2. CRITICAL: Do NOT use any Markdown formatting. No asterisks (**), no hashtags (#), no backticks (`), and no bolding symbols.
            3. Use standard sentence case and normal punctuation.
            4. If the data results are empty, state clearly that no records were found.
            5. Present any lists using simple numbers (1., 2.) or bullet points (- ) that are readable as plain text.
            6. The summary should be easy to read in any plain text application.
            """
        ) | self.llm | StrOutputParser()