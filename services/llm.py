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
            
            # Skip live connectivity test for local/Ollama endpoints — they don't validate real API keys
            # and may not be running at configuration time. Test only for real external APIs.
            is_local_or_ollama = (
                "localhost" in base_url
                or "127.0.0.1" in base_url
                or "ollama" in api_key.lower()
                or api_key.lower() in ["ollama", "none", "local"]
            )
            
            if validate_key and not is_local_or_ollama:
                if not self.test_api_key(api_key, base_url, model, headers):
                    raise ValueError(self.last_error or "Invalid API key or connection failed. Please check your credentials and network access.")
            elif is_local_or_ollama:
                print(f"   [Ollama/Local] Skipping live API key validation for local endpoint.")
            
            # Store configuration details
            self.config_details = {
                "api_key": api_key[:10] + "..." if len(api_key) > 10 else api_key,
                "base_url": base_url,
                "model": model,
                "headers": list(headers.keys()) if headers else None
            }
            
            model_kwargs = {}
            if "nemotron" in model.lower():
                model_kwargs["extra_body"] = {
                    "chat_template_kwargs": {"enable_thinking": True},
                    "reasoning_budget": 16384
                }
            
            # Create the LLM instance
            self.llm = ChatOpenAI(
                openai_api_base=base_url,
                openai_api_key=api_key,
                model=model,
                temperature=1.0 if "nemotron" in model.lower() else 0.0,
                max_tokens=16384 if "nemotron" in model.lower() else settings.llm_max_output_tokens,
                top_p=0.95 if "nemotron" in model.lower() else 1.0,
                timeout=120,
                default_headers=headers,
                model_kwargs=model_kwargs
            )
            
            self.configured = True
            print(f"LLM configured successfully with model: {model}")
            return True
            
        except Exception as e:
            err_str = str(e)
            # Self-healing: If model not found, try to fallback to default
            if "404" in err_str and model != settings.llm_model_name:
                print(f"⚠️ Model '{model}' not found. Attempting fallback to default '{settings.llm_model_name}'...")
                return self.configure(api_key, base_url, settings.llm_model_name, headers, validate_key)
                
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
    
    def create_sql_chain(self, db, dialect="postgresql"):
        """Create SQL query chain"""
        if not self.is_configured():
            raise RuntimeError("LLM not configured. Cannot create SQL chain.")
            
        prompt = ChatPromptTemplate.from_template(
            f"""You are a {dialect.upper()} expert. Generate syntactically correct SQL for the following question.
            Return only SQL. Use this database schema:
            {{schema_info}}

            Question: {{Question}}

            CRITICAL RULES:
            - Use ONLY the exact column names provided in the schema above
            - Do NOT use generic column names like "date"; verify the exact column name from the schema
            - Double-check that every referenced column exists in the schema
            - Use modular CTEs (WITH clauses) for complex logic involving more than 3 tables
            - For date/timestamp columns, verify the exact column name from the schema (e.g., order_date, created_at)
            - Check join connectivity before generating; do not assume join paths if keys are not visible in the capsules
            - Return only the SQL query, no explanations or markdown
            - Use exact syntax for {dialect.upper()}.
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

            CRITICAL GROUNDING RULES:
            1. ONLY answer based on the provided "Query Results". 
            2. If the results say "Insufficient schema context", inform the user that the specific data requested was not found.
            3. NEVER invent numbers (e.g., do not say 'There are 50 tables' if the results don't specifically contain that number).
            4. If the results are empty, state that no information was found for that specific question.
            5. Use plain text only. NO Markdown. NO asterisks (**), NO bolding, NO backticks.
            """
        ) | self.llm | StrOutputParser()

    def create_concept_extraction_chain(self):
        """Create a chain to extract business concepts and roles for graph-based discovery"""
        if not self.is_configured():
            raise RuntimeError("LLM not configured.")
        prompt = ChatPromptTemplate.from_template(
            """You are a Database Architect. Analyze the user's question and extract the core business concepts.
            Question: {Question}
            Identify:
            1. ANCHOR ENTITIES: Main business nouns (e.g. Orders, Employees).
            2. ATTRIBUTES: Needed fields (e.g. status, tax, region).
            
            Return a comma-separated list of 5-10 technical keywords for schema searching.
            Keywords:"""
        )
        return prompt | self.llm | StrOutputParser()

    def create_schema_planner_chain(self):
        """Create a chain that evaluates if the schema context is sufficient for the query"""
        if not self.is_configured():
            raise RuntimeError("LLM not configured.")
        prompt = ChatPromptTemplate.from_template(
            """You are a Query Planner. Evaluate if the provided schema context is sufficient to answer the question.
            Question: {Question}
            
            Current Schema Context:
            {schema_context}
            
            Return ONLY a JSON object:
            {{
                "status": "ready" or "need_more_schema",
                "missing_concepts": ["list", "of", "missing"],
                "next_search_terms": ["keywords", "for", "missing", "entities"]
            }}
            """
        )
        return prompt | self.llm | StrOutputParser()

    def create_keyword_extraction_chain(self):
        """Create a chain to extract high-level keywords/entities for schema searching"""
        prompt = ChatPromptTemplate.from_template(
            """
            You are a database expert and business analyst. Given a natural language question about an ERP database, 
            extract the most important technical keywords and their common abbreviations to help find relevant tables.
            
            USER QUESTION: {Question}
            
            RULES:
            1. Extract nouns and entities (e.g., 'customer', 'invoice', 'ledger').
            2. If you see 'General Ledger', include 'gl'.
            3. If you see 'Accounts Payable', include 'ap'.
            4. If you see 'Accounts Receivable', include 'ar'.
            5. If you see 'Purchase Order', include 'po'.
            6. If you see 'Goods Receipt', include 'grn'.
            7. If you see 'Human Resources' or 'Employee', include 'hr'.
            8. Include the schema name if mentioned (e.g., 'sales', 'finance').
            9. Return ONLY a comma-separated list of keywords.
            
            KEYWORDS:"""
        )
        return prompt | self.llm | StrOutputParser()

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

    def create_sql_generation_chain(self, dialect="postgresql"):
        """Step 2: Generate final SQL from filtered schema context"""
        if not self.is_configured():
            raise RuntimeError("LLM not configured.")

        prompt = ChatPromptTemplate.from_template(
            f"""You are a strict {dialect.upper()} SQL generator. Your ONLY job is to write SQL using the EXACT tables and columns listed below.

AVAILABLE SCHEMA (you may ONLY use these tables and columns):
{{schema_context}}

User's Question: {{Question}}

ABSOLUTE RULES - Violations will cause runtime errors:
1. DO NOT use ANY table not explicitly listed in the schema above.
2. DO NOT invent or guess column names. Use ONLY the exact column names shown above.
3. DO NOT reference any table from your training data or general knowledge.
4. Make your best effort to construct the query using the available schema context, even if some column names require an educated guess. Only return SELECT 'Insufficient schema context to answer this question' AS message; if the provided tables are completely irrelevant to the question.
5. Return ONLY the raw SQL statement. No markdown, no ```, no explanation.
6. Use correct {dialect.upper()} syntax.
7. Always limit the results unless the question requires a full count. (Use LIMIT for Postgres/MySQL, TOP for MSSQL, FETCH FIRST for Oracle).

SQL Query:"""
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