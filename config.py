from pydantic_settings import BaseSettings
from pydantic import Field, ConfigDict
from typing import Optional
import os

class Settings(BaseSettings):
    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        protected_namespaces=('settings_',),
        extra="allow"
    )
    
    # Database configuration
    db_host: str = Field("", env="DB_HOST")
    db_port: str = Field("5432", env="DB_PORT")
    db_name: str = Field("", env="DB_NAME")
    db_user: str = Field("", env="DB_USER")
    db_password: str = Field("", env="DB_PASSWORD")
    
    # LLM configuration
    krutim_cloud_api_key: str = Field("", env="KRUTIM_CLOUD_API_KEY")
    openai_api_base: str = Field("https://cloud.olakrutrim.com/v1", env="OPENAI_API_BASE")
    llm_model_name: str = Field("Llama-3.3-70B-Instruct", env="MODEL_NAME")
    
    # Application settings
    app_title: str = "Database Query API"
    app_version: str = "1.0.0"
    app_description: str = "API for natural language to SQL conversion and execution"
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        # Debug: Print loaded environment variables
        print("🔧 Environment variables loaded:")
        print(f"   DB_HOST: {self.db_host}")
        print(f"   DB_NAME: {self.db_name}")
        print(f"   DB_USER: {self.db_user}")
        print(f"   KRUTIM_CLOUD_API_KEY: {self.krutim_cloud_api_key[:10]}..." if self.krutim_cloud_api_key else "   KRUTIM_CLOUD_API_KEY: (not set)")
        print(f"   OPENAI_API_BASE: {self.openai_api_base}")
        print(f"   MODEL_NAME: {self.llm_model_name}")

settings = Settings()
