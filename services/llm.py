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
                or "10." in base_url
                or "192.168." in base_url
                or "172.1" in base_url
                or "ollama" in api_key.lower()
                or api_key.lower() in ["ollama", "none", "not-needed", "empty", "local"]
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
        api_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY")
        
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

    def create_sql_generation_chain(self, dialect="postgresql"):
        """Generate high-quality SQL using a structured think → plan → write → verify approach"""
        if not self.is_configured():
            raise RuntimeError("LLM not configured.")

        prompt = ChatPromptTemplate.from_template(
            f"""You are an expert {dialect.upper()} SQL engineer with deep knowledge of query optimization, JOIN strategies, and window functions.

## DATABASE SCHEMA
The ONLY tables and columns you are allowed to use:
{{schema_context}}

## USER QUESTION
{{Question}}

## YOUR TASK
Follow these steps in your head before writing the final SQL:

STEP 1 — UNDERSTAND
- What data does the user want? (rows, aggregates, trends, comparisons, rankings, structural/metadata info?)
- What filters, groupings, or sort orders are implied — including relative dates ("last month", "this quarter", "past 7 days"), fuzzy/partial text matches, and implicit "top/bottom N" phrasing?
- If the question is ambiguous or underspecified, pick the most reasonable interpretation based on common business usage and proceed — do not stop or ask for clarification.

STEP 2 — MAP TO SCHEMA
- Which tables contain the required data?
- Identify all necessary JOIN keys between those tables.
- Confirm every column you plan to use exists in the schema above.
- If a needed column is ambiguous, qualify it with its table name.

STEP 3 — PLAN THE QUERY STRUCTURE
- Simple lookup → plain SELECT with WHERE
- Aggregation (count/sum/avg/min/max) → GROUP BY + HAVING
- Multiple related tables → JOIN with explicit ON conditions (INNER/LEFT/RIGHT/FULL as the question implies)
- 3+ tables, self-referencing, or reusable intermediate results → CTEs (WITH clauses) for readability
- Hierarchical or recursive data (org charts, bill of materials, category trees, threads) → recursive CTE (WITH RECURSIVE or the dialect's equivalent)
- Rankings, running totals, moving averages, percent-of-total → window functions (ROW_NUMBER, RANK, DENSE_RANK, SUM/AVG/COUNT OVER, LAG/LEAD)
- Time-series trends or period bucketing → GROUP BY date truncation/formatting at the requested granularity (day/week/month/quarter/year), using the dialect's date-truncation function
- Pivot-style breakdowns ("X by category as columns") → conditional aggregation with CASE WHEN inside SUM/COUNT/AVG
- Existence / non-existence checks → EXISTS / NOT EXISTS, or LEFT JOIN ... IS NULL
- Membership against a fixed set or subquery result → IN / NOT IN (prefer NOT EXISTS for large or nullable sets)
- Combining or comparing multiple result sets → UNION / UNION ALL / INTERSECT / EXCEPT where the dialect supports it
- Multi-level or grouped subtotals ("with subtotals/grand total") → ROLLUP / CUBE / GROUPING SETS where the dialect supports it
- Free-text, partial, or fuzzy matches → LIKE/ILIKE, or the dialect's full-text search functions
- Structural/metadata questions (list tables, describe columns, row counts) → query the schema-metadata context provided above if present

STEP 4 — WRITE THE SQL
Apply these quality rules:
- Always alias tables (e.g., orders o, customers c)
- Use COALESCE to handle NULLs in aggregations; use NULLIF to guard against division by zero
- Add meaningful column aliases in SELECT (e.g., AS total_revenue)
- Apply LIMIT 100 only as a safety default for open-ended row listings — do NOT apply it when the question asks for all matching rows, a specific top-N/bottom-N count, a single aggregate/summary row, or any result that would legitimately exceed 100 rows
- Use proper {dialect.upper()} syntax for date functions, string ops, casting, and row-limiting (e.g., MSSQL uses TOP, Oracle uses FETCH FIRST N ROWS ONLY, most others use LIMIT)

STEP 5 — VERIFY
- Every table referenced exists in the schema.
- Every column referenced exists in its table.
- All JOINs have matching data types on both sides.
- No hallucinated table or column names.
- The query shape actually matches what was asked (no unrequested LIMIT, no dropped filters/groupings).

## ABSOLUTE CONSTRAINTS
1. Use ONLY tables and columns explicitly listed in the schema above. Check each table's column list carefully — do NOT assume a 'date' or 'created_at' column exists on a table (such as 'orders') unless it is explicitly listed in that table's columns.
2. Perform flexible schema inference: map business terms, synonyms, and related concepts (e.g. loans, awards, profile, activity, status) to the closest matching tables and columns available in the schema.
3. Only if the question is completely unrelated to any table or column in the schema, return:
   SELECT 'Insufficient schema context to answer this question' AS message;
4. Return ONLY the final raw SQL statement. No markdown, no ```, no explanation text.

SQL Query:"""
        )
        return prompt | self.llm | StrOutputParser()

    def create_sql_repair_chain(self, dialect="postgresql"):
        """Repair a failed SQL query given the error message and schema"""
        if not self.is_configured():
            raise RuntimeError("LLM not configured.")

        prompt = ChatPromptTemplate.from_template(
            f"""You are an expert {dialect.upper()} SQL debugger.

## DATABASE SCHEMA
{{schema_context}}

## ORIGINAL QUESTION
{{Question}}

## FAILED SQL
{{failed_sql}}

## ERROR MESSAGE
{{error_message}}

## YOUR TASK
Fix the SQL so it runs correctly. CRITICAL INSTRUCTIONS:
- If error is "column X.column_name does not exist" (e.g. "column o.date does not exist"): Inspect table X in {{schema_context}}. If table X does NOT have that column (e.g., if 'orders' does NOT have a 'date' column), DO NOT use X.column_name! Use a table that actually contains a date column (e.g., 'account.date' or 'loan.date') or remove the invalid column reference.
- Column name typo or mismatch → replace with exact name present in schema
- Ambiguous column → qualify with table alias
- Wrong JOIN key → use the correct foreign key from schema
- Syntax error → fix to valid {dialect.upper()} syntax
- Missing GROUP BY → add all non-aggregated SELECT columns
- Type mismatch in JOIN or WHERE → cast appropriately
- Aggregate function used in WHERE → move that condition to HAVING
- Subquery returns more than one row → wrap with IN/EXISTS, or aggregate it down to one row
- Division by zero → guard the denominator with NULLIF(denominator, 0)
- Window function used directly in WHERE/HAVING → move the filter to an outer query wrapping the windowed SELECT
- Dialect-specific function or row-limiting syntax not supported → substitute the correct {dialect.upper()} equivalent

Return ONLY the corrected raw SQL. No explanation, no markdown.

Fixed SQL:"""
        )
        return prompt | self.llm | StrOutputParser()

    def create_explanation_chain(self):
        """Generate a rich, structured natural-language response grounded in query results"""
        if not self.is_configured():
            raise RuntimeError("LLM not configured. Cannot create explanation chain.")

        return ChatPromptTemplate.from_template(
            """You are a professional data analyst presenting findings to a business stakeholder.

User's Question: {Question}
Database Schema Used: {schema_info}
Query Results: {results}

YOUR TASK:
Write a clear, well-structured answer that directly addresses the user's question using ONLY the data in "Query Results".

STRUCTURE GUIDELINES:
1. Start with a one-sentence direct answer to the question.
2. Present the key data points clearly (use numbered lists for multiple items).
3. Highlight the most important finding, trend, or outlier if present.
4. If results are empty, say clearly: "No records were found matching this query."
5. If results contain "Insufficient schema context" or indicate insufficient data/schema to answer the question, do NOT say "Insufficient schema context" or "The required data could not be found". Instead, analyze the "Database Schema Used" and write the response by proposing 3 likely, relevant natural language queries the user could run. These suggested queries must directly reference actual table names and column names present in the schema to guide the user (e.g. "list all the tables", "list the dbo.assets table with asset name and cost", or "show all dbo.employees").
6. End with a brief summary sentence only if there are 5 or more result rows.

STRICT FORMATTING RULES:
- Plain text only. NO Markdown. NO asterisks (**). NO hashtags (#). NO backticks (`).
- Use simple numbered lists (1. 2. 3.) or dashes (- ) for listing items.
- Do NOT invent any numbers, names, or facts not present in the query results (except when proposing the 3 likely queries under guideline 5 using the provided schema).
- Keep the response concise: aim for 3-10 sentences for small result sets, up to 20 for large ones.
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
            You are a database expert and business analyst. Given a natural language question about a database
            in any domain, extract the most important technical keywords and their common abbreviations to help
            find relevant tables.

            USER QUESTION: {Question}

            RULES:
            1. Extract nouns and entities mentioned or implied by the question (e.g., 'customer', 'invoice', 'patient', 'shipment', 'enrollment', 'ledger').
            2. For any multi-word business or technical term, also include its common industry abbreviation if one plausibly exists — infer this from general domain knowledge rather than a fixed list. Examples of the pattern (not an exhaustive list, and not limited to this domain): 'General Ledger' → gl, 'Accounts Payable' → ap, 'Accounts Receivable' → ar, 'Purchase Order' → po, 'Goods Receipt Note' → grn, 'Human Resources' → hr, 'Electronic Health Record' → ehr, 'Stock Keeping Unit' → sku, 'Customer Relationship Management' → crm, 'Key Performance Indicator' → kpi. Apply this same expansion logic to whatever domain the question is actually about (finance, healthcare, retail, logistics, education, manufacturing, SaaS, etc.).
            3. Include the schema or module name if mentioned (e.g., 'sales', 'finance', 'clinical', 'inventory').
            4. Return ONLY a comma-separated list of keywords.

            KEYWORDS:"""
        )
        return prompt | self.llm | StrOutputParser()

    def create_table_search_mongodb_chain(self):
        """Step 1: Generate a MongoDB query to find relevant tables from metadata"""
        if not self.is_configured():
            raise RuntimeError("LLM not configured.")

        prompt = ChatPromptTemplate.from_template(
            """You are a database expert. Your task is to generate a MongoDB find() query to search for relevant tables in a schema metadata collection.

            Metadata Collection Schema (collection: table_metadata; exact fields may vary slightly by deployment):
            - table: table name
            - schema: schema name (e.g. 'public', 'dbo')
            - database: database name
            - host: host name
            - column_names: array of strings (e.g., ["id", "name", "created_at"])
            - description / tags: optional free-text or keyword fields — if present in a given document, also match against them

            User's Question: {Question}

            Instructions:
            - Return ONLY a valid JSON object used as the filter for MongoDB find().
            - The filter should use $or and $regex to search across all relevant text fields (at minimum "table" and "column_names"; also "description"/"tags" if the question's terms look conceptual rather than literal).
            - Make the regex case-insensitive using $options: "i".
            - Only return the raw JSON object.
            
            Example Output:
            {{"$or": [{{"table": {{"$regex": "user", "$options": "i"}}}}, {{"column_names": {{"$regex": "email", "$options": "i"}}}}]}}
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
            - Return ONLY a valid JSON object with keys: "filter", "projection", and optionally "sort" and "limit"
            - "filter" is the MongoDB query filter (the first argument to find())
            - "projection" is the fields to return (the second argument to find()). Use 1 to include, 0 to exclude. Always exclude "_id" unless specifically asked.
            - Use ONLY the exact field names from the schema above, including dot-notation for nested/embedded fields (e.g., "address.city")
            - Combine multiple conditions with $and / $or / $nor as the question requires
            - For membership against a list of values, use $in / $nin
            - For array fields, use $all (contains all values), $elemMatch (element matching multiple conditions), and $size (array length)
            - For field presence or type checks, use $exists and $type
            - For free-text search across a field, use $regex with $options: "i" for case-insensitive partial/fuzzy matching; if the schema indicates a text index, $text with $search is also acceptable
            - For numeric or date comparisons use $gt, $gte, $lt, $lte, $eq, $ne (date ranges: combine $gte/$lte on the date field, resolving relative phrases like "last month" or "past 7 days" to concrete ISO date bounds)
            - For cross-field or computed comparisons, use $expr
            - For geospatial queries, use native MongoDB operators like $near, $nearSphere, $geoWithin, or $geoIntersects if the schema contains 2dsphere indexes or coordinates.
            - If calculating distance manually via $expr, keep the formula as concise as possible to avoid truncation.
            - For sorting, add a "sort" key with field and direction (1=asc, -1=desc); multiple sort keys are allowed
            - For limiting results, add a "limit" key with an integer value; omit it (or use a generous value) when the question asks for all matching documents
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