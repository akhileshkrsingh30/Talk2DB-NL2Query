from fastapi import Depends, HTTPException, status
from typing import Annotated
import psycopg2
from psycopg2.extras import RealDictCursor

from services.registry import service_registry
from services.database import DatabaseService
from services.llm import LLMService
from services.sharing import SharingService
from services.billing.billing_service import BillingService

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
        return service_registry.get_llm_service()
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