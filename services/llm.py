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
                "max_tokens": 10
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
        
    def configure(self, api_key: str, base_url: str = None, model: str = None, headers: Optional[Dict[str, str]] = None) -> bool:
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
            
            # Test the API key first
            if not self.test_api_key(api_key, base_url, model, headers):
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
                max_tokens=1024,
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
    
    def is_configured(self) -> bool:
        """Check if LLM is configured"""
        return self.configured and self.llm is not None
    
    def get_llm(self):
        """Get LLM instance"""
        if not self.is_configured():
            raise RuntimeError("LLM not configured. Please configure the LLM service first.")
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
            Return only SQL. Use these tables: {table_info}
            Question: {Question}
            schema_info: {schema_info}
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
    """You are a PostgreSQL expert. Generate syntactically correct SQL for the following question.
    Return only SQL. Use these tables:

    Question: {Question}
    schema_info: {schema_info}
    CRITICAL RULES:
    - Use ONLY the exact column names provided in the table schema above
    - Double-check that every column referenced exists in the schema
    - Use proper PostgreSQL syntax
    - For date/timestamp columns, verify the exact column name from the schema
    - Common date column names: order_date, created_at, date, timestamp
    - If a column doesn't exist, use the closest matching column from the schema
    - Return only the SQL query, no explanations or markdown
    - Do not assume column names - only use columns explicitly listed in the schema
    
    Example corrections:
    - If schema has "order_date" instead of "date", use "order_date"
    - If schema has "created_at" instead of "date", use "created_at"
    """
) | self.llm | StrOutputParser()