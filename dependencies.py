from fastapi import Depends, HTTPException, status, Header
from typing import Annotated, Optional
import psycopg2
import requests
import re
from psycopg2.extras import RealDictCursor

from services.registry import service_registry
from services.database import DatabaseService
from services.llm import LLMService
from services.sharing import SharingService
from services.mongodb import MongoDBService
from services.billing.billing_service import BillingService
from services.mem0_service import Mem0Service
from config import settings
import os

def get_db_service() -> DatabaseService:
    """Dependency to get database service instance"""
    try:
        service = service_registry.get_db_service()
        # If not connected, try to auto-connect using environment settings
        if not service.is_connected():
            if all([settings.db_host, settings.db_port, settings.db_user, settings.db_password]):
                try:
                    service.connect({
                        "host": settings.db_host,
                        "port": settings.db_port,
                        "database": settings.db_name,
                        "user": settings.db_user,
                        "password": settings.db_password,
                        "db_type": settings.db_type
                    })
                except Exception:
                    pass # Fail silently, let subsequent checks raise appropriate error
        return service
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

def get_llm_service() -> LLMService:
    """Dependency to get LLM service instance"""
    try:
        service = service_registry.get_llm_service()
        # Proactive auto-configuration if not already configured
        if not service.is_configured():
            api_key = settings.krutim_cloud_api_key or settings.openai_api_key or os.getenv("OPENAI_API_KEY")
            if api_key and api_key.strip():
                try:
                    service.configure(
                        api_key=api_key,
                        base_url=settings.openai_api_base or os.getenv("OPENAI_API_BASE"),
                        model=settings.llm_model_name,
                        validate_key=False
                    )
                except Exception:
                    pass # Fail silently, let the endpoint handle the error
        return service
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

def get_sharing_service() -> SharingService:
    """Dependency to get sharing service instance"""
    try:
        return service_registry.get_sharing_service()
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

def get_billing_service() -> BillingService:
    """Dependency to get billing service instance"""
    try:
        return service_registry.get_billing_service()
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

def get_db_connection(
    db_service: Annotated[DatabaseService, Depends(get_db_service)]
) -> psycopg2.extensions.connection:
    """Dependency to get database connection"""
    if not db_service.is_connected():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Database not connected. Please connect first."
        )
    
    try:
        # Create a new connection for this request
        conn = db_service.create_connection()
        return conn
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create database connection: {str(e)}"
        )

def get_llm(
    llm_service: Annotated[LLMService, Depends(get_llm_service)]
):
    """Dependency to get LLM instance"""
    if not llm_service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="LLM not configured. Please check API key."
        )
    return llm_service.get_llm()

def get_mongodb_service() -> MongoDBService:
    """Dependency to get MongoDB service instance"""
    try:
        return service_registry.get_mongodb_service()
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

def get_mem0_service() -> Mem0Service:
    """Dependency to get Mem0 service instance"""
    try:
        return service_registry.get_mem0_service()
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


def get_user_id_from_token(token: str) -> Optional[str]:
    import base64
    import json
    try:
        parts = token.split(".")
        if len(parts) >= 2:
            payload_b64 = parts[1]
            # Fix base64 padding
            padding = "=" * (4 - len(payload_b64) % 4)
            payload_decoded = base64.urlsafe_b64decode(payload_b64 + padding).decode("utf-8")
            payload_data = json.loads(payload_decoded)
            
            # Check for userId, user_id, or sub
            uid = payload_data.get("userId") or payload_data.get("user_id") or payload_data.get("sub")
            if uid is not None:
                return str(uid)
    except Exception:
        pass
    return None

def verify_token(authorization: Annotated[Optional[str], Header()] = None) -> str:
    """
    Authentication removed/bypassed. 
    Attempts to extract identity from the authorization header if provided,
    otherwise falls back to the default administrator 'jetly.2492@gmail.com'.
    """
    default_user = "jetly.2492@gmail.com"
    
    if not authorization:
        return default_user
    
    try:
        # Try to parse the token directly to see if we can extract the user ID
        token_str = authorization.replace("Bearer ", "").strip()
        user_id_from_token = get_user_id_from_token(token_str)
        if user_id_from_token:
            return user_id_from_token
            
        # Try validation with external API
        response = requests.get(
            settings.auth_api_url, 
            headers={"Authorization": authorization},
            timeout=3
        )
        
        if response.status_code == 200:
            match = re.search(r"Hello, (.+?)! This is a protected API", response.text)
            if match:
                return match.group(1)
    except Exception:
        pass
        
    return default_user