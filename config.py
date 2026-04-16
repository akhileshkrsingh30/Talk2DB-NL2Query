from pydantic_settings import BaseSettings
from pydantic import Field, ConfigDict
from typing import Optional
import os
from dotenv import load_dotenv

# Explicitly load .env from the current directory
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(env_path)
print(f"Loading .env from: {env_path} (exists: {os.path.exists(env_path)})")

class Settings(BaseSettings):
    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        protected_namespaces=('settings_',),
        extra="allow"
    )
    
    # Database configuration
    db_type: str = Field("postgresql", env="DB_TYPE")
    db_host: str = Field("", env="DB_HOST")
    db_port: str = Field("5432", env="DB_PORT")
    db_name: str = Field("", env="DB_NAME")
    db_user: str = Field("", env="DB_USER")
    db_password: str = Field("", env="DB_PASSWORD")
    
    # LLM configuration
    krutim_cloud_api_key: str = Field("", env="KRUTIM_CLOUD_API_KEY")
    openai_api_key: str = Field("", env="OPENAI_API_KEY")
    openai_api_base: str = Field("", env="OPENAI_API_BASE")
    llm_model_name: str = Field("gpt-5.2", env="LLM_MODEL_NAME")
    llm_max_context_chars: int = Field(100000, env="LLM_MAX_CONTEXT_CHARS")
    llm_max_output_tokens: int = Field(4096, env="LLM_MAX_OUTPUT_TOKENS")
    
    # Billing configuration (Price per 1M tokens in USD)
    price_input_1m: float = Field(0.15, env="BILLING_PRICE_INPUT_1M")
    price_output_1m: float = Field(0.60, env="BILLING_PRICE_OUTPUT_1M")
    
    # MongoDB configuration
    mongo_uri: str = Field("mongodb://localhost:27017/", env="MONGO_URI")
    mongo_db_name: str = Field("ValoDSS", env="MONGO_DB_NAME")
    
    # Neo4j configuration
    neo4j_uri: str = Field("bolt://localhost:7687", env="NEO4J_URI")
    neo4j_user: str = Field("neo4j", env="NEO4J_USER")
    neo4j_password: str = Field("password", env="NEO4J_PASSWORD")
    
    # Application settings
    app_title: str = "Database Query API"
    app_version: str = "1.0.0"
    app_description: str = "API for natural language to SQL conversion and execution"
    
    # Auth configuration
    auth_api_url: str = Field("http://10.199.207.78:8080/jwt-0.0.1-SNAPSHOT/api/protected", env="AUTH_API_URL")
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        # Debug: Print loaded environment variables
        print("Environment variables loaded:")
        print(f"   DB_TYPE: {self.db_type}")
        print(f"   DB_HOST: {self.db_host}")
        print(f"   DB_NAME: {self.db_name}")
        print(f"   DB_USER: {self.db_user}")
        print(f"   KRUTIM_CLOUD_API_KEY: {self.krutim_cloud_api_key[:10]}..." if self.krutim_cloud_api_key else "   KRUTIM_CLOUD_API_KEY: (not set)")
        print(f"   OPENAI_API_KEY: {self.openai_api_key[:10]}..." if self.openai_api_key else "   OPENAI_API_KEY: (not set)")
        print(f"   OPENAI_API_BASE: {self.openai_api_base}")
        print(f"   MODEL_NAME: {self.llm_model_name}")
        print(f"   MONGO_URI: {self.mongo_uri}")
        print(f"   MONGO_DB_NAME: {self.mongo_db_name}")
        print(f"   NEO4J_URI: {self.neo4j_uri}")
        print(f"   NEO4J_USER: {self.neo4j_user}")
        print(f"   MAX_CONTEXT_CHARS: {self.llm_max_context_chars}")
        print(f"   MAX_OUTPUT_TOKENS: {self.llm_max_output_tokens}")
        
        env_path = os.path.join(os.getcwd(), ".env")
        print(f"   Current Working Directory: {os.getcwd()}")
        print(f"   .env file exists: {os.path.exists(env_path)}")

settings = Settings()
