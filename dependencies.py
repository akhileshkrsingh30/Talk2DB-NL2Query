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
from services.billing.billing_service import BillingService
from services.mongodb import MongoDBService
from services.neo4j_service import Neo4jService
from config import settings
import os

def get_db_service() -> DatabaseService:
    """Dependency to get database service instance"""
    try:
        return service_registry.get_db_service()
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

def get_neo4j_service() -> Neo4jService:
    """Dependency to get Neo4j service instance"""
    try:
        return service_registry.get_neo4j_service()
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

def verify_token(authorization: Annotated[Optional[str], Header()] = None) -> str:
    """
    Validate token with external API and extract identity.
    Flow: Backend forwards JWT -> External API -> Parse Identity
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token is missing!"
        )
    
    try:
        # Validate token with external API
        response = requests.get(
            settings.auth_api_url, 
            headers={"Authorization": authorization},
            timeout=10
        )
        
        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid or expired token"
            )

        # Extract identity from API response
        # Format: "Hello, jyoti.raut@softelnetworks.com! This is a protected API."
        match = re.search(r"Hello, (.+?)! This is a protected API", response.text)
        if not match:
            # If the format is slightly different, we try to preserve the username
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Failed to parse identity from auth service"
            )
        
        username = match.group(1)
        return username
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token validation failed: {str(e)}"
        )