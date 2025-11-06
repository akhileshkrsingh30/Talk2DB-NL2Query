from fastapi import APIRouter, Depends, HTTPException, status
from typing import Annotated
from pydantic import BaseModel, Field

from services.llm import LLMService
from dependencies import get_llm_service

router = APIRouter(prefix="/llm", tags=["llm-config"])

class LLMConfigRequest(BaseModel):
    api_key: str = Field(..., description="Krutim AI API key")
    api_base: str = Field("https://api.krutim.ai/v1", description="Krutim AI API base URL")
    model: str = Field("llama-3-70b-instruct", description="Model name")

class LLMConfigResponse(BaseModel):
    status: str = Field(..., description="Configuration status")
    message: str = Field(..., description="Detailed message")
    model: str = Field(..., description="Configured model name")

@router.post("/configure", response_model=LLMConfigResponse, responses={400: {"model": dict}})
async def configure_llm(
    config: LLMConfigRequest,
    llm_service: Annotated[LLMService, Depends(get_llm_service)]
):
    """Configure the LLM service with Krutim AI credentials"""
    try:
        success = llm_service.configure(
            api_key=config.api_key,
            base_url=config.api_base,
            model=config.model
        )
        
        if success:
            return LLMConfigResponse(
                status="success",
                message="LLM configured successfully",
                model=config.model
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to configure LLM"
            )
            
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"LLM configuration failed: {str(e)}"
        )

@router.get("/status", response_model=LLMConfigResponse)
async def get_llm_status(
    llm_service: Annotated[LLMService, Depends(get_llm_service)]
):
    """Get current LLM configuration status"""
    if llm_service.is_configured():
        return LLMConfigResponse(
            status="configured",
            message="LLM is configured and ready to use",
            model="llama-3-70b-instruct"  # This would ideally come from the service
        )
    else:
        return LLMConfigResponse(
            status="not_configured",
            message="LLM is not configured. Please configure it first.",
            model="none"
        )