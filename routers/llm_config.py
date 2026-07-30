from fastapi import APIRouter, Depends, HTTPException, status
from typing import Annotated
from pydantic import BaseModel, Field

from config import settings
from services.llm import LLMService
from dependencies import get_llm_service, verify_token
from typing import Optional

router = APIRouter(prefix="/llm", tags=["llm-config"])

class LLMConfigRequest(BaseModel):
    api_key: Optional[str] = Field(None, description="LLM API key (falls back to .env if not provided)")
    api_base: Optional[str] = Field(None, description="LLM API base URL (falls back to .env if not provided)")
    model: Optional[str] = Field(None, description="Model name (falls back to .env if not provided)")
    validate_key: Optional[bool] = Field(True, description="Whether to validate API key and connection during configuration")

class LLMConfigResponse(BaseModel):
    status: str = Field(..., description="Configuration status")
    message: str = Field(..., description="Detailed message")
    model: str = Field(..., description="Configured model name")

@router.post("/configure", response_model=LLMConfigResponse, responses={400: {"model": dict}})
async def configure_llm(
    config: LLMConfigRequest,
    llm_service: Annotated[LLMService, Depends(get_llm_service)],
    current_user: Annotated[str, Depends(verify_token)]
):
    """Configure the LLM service credentials"""
    try:
        # Fallback logic
        api_key = config.api_key or settings.openai_api_key
        api_base = config.api_base or settings.openai_api_base
        model = config.model or settings.llm_model_name

        success = llm_service.configure(
            api_key=api_key,
            base_url=api_base,
            model=model,
            validate_key=config.validate_key if config.validate_key is not None else True
        )
        
        if success:
            return LLMConfigResponse(
                status="success",
                message="LLM configured successfully",
                model=model
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
        config = llm_service.get_config_details()
        return LLMConfigResponse(
            status="configured",
            message="LLM is configured and ready to use",
            model=config.get("model", "unknown") if config else "unknown"
        )
    else:
        return LLMConfigResponse(
            status="not_configured",
            message=f"LLM is not configured. (Using model: {settings.llm_model_name})",
            model="none"
        )