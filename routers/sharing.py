from fastapi import APIRouter, Depends, HTTPException, status, Request
from typing import Annotated, List, Optional
from pydantic import BaseModel, Field

from schemas import SharedResult, SharedResultMetadata, QueryResult, ShareResponse
from services.sharing import SharingService
from dependencies import get_sharing_service

router = APIRouter(prefix="/sharing", tags=["sharing"])

class CreateShareRequest(BaseModel):
    result: QueryResult
    expiry_hours: Optional[int] = Field(24, description="Hours until the shared result expires", ge=1, le=168)

@router.post("/", response_model=ShareResponse)
async def create_share(
    payload: CreateShareRequest,
    request: Request,
    sharing_service: Annotated[SharingService, Depends(get_sharing_service)]
):
    """Share an already-computed query result directly (e.g. from the chat UI or client-side history),
    without depending on the server's own (per-request, often-empty) query history index."""
    share_id = sharing_service.share_result(payload.result.model_dump(), payload.expiry_hours)
    shared_data = sharing_service.get_shared_result(share_id)
    base_url = str(request.base_url).rstrip('/')
    return ShareResponse(
        share_id=share_id,
        share_url=f"{base_url}/sharing/{share_id}",
        expires_at=shared_data["expires_at"]
    )

@router.get("/{share_id}", response_model=SharedResult)
async def get_shared_result(
    share_id: str,
    sharing_service: Annotated[SharingService, Depends(get_sharing_service)]
):
    """Get a shared query result by ID"""
    shared_data = sharing_service.get_shared_result(share_id)
    
    if not shared_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shared result not found or expired"
        )
    
    metadata = SharedResultMetadata(
        id=shared_data["id"],
        created_at=shared_data["created_at"],
        expires_at=shared_data["expires_at"],
        access_count=shared_data["access_count"],
        last_accessed=shared_data["last_accessed"],
        query=shared_data["result"]["query"],
        sql_queries_count=len(shared_data["result"]["sql_queries"])
    )
    
    return SharedResult(
        metadata=metadata,
        result=shared_data["result"]
    )

@router.get("/", response_model=List[SharedResultMetadata])
async def list_shared_results(
    sharing_service: Annotated[SharingService, Depends(get_sharing_service)],
    limit: int = 50
):
    """List all active shared results (metadata only)"""
    results = sharing_service.list_shared_results(limit)
    
    return [
        SharedResultMetadata(
            id=r["id"],
            created_at=r["created_at"],
            expires_at=r["expires_at"],
            access_count=r["access_count"],
            last_accessed=r["last_accessed"],
            query=r["query"],
            sql_queries_count=r["sql_queries_count"]
        )
        for r in results
    ]

@router.delete("/{share_id}")
async def delete_shared_result(
    share_id: str,
    sharing_service: Annotated[SharingService, Depends(get_sharing_service)]
):
    """Delete a shared result (admin function)"""
    sharing_service._delete_shared_result(share_id)
    return {"message": f"Shared result {share_id} deleted"}

@router.post("/cleanup")
async def cleanup_expired_results(
    sharing_service: Annotated[SharingService, Depends(get_sharing_service)]
):
    """Clean up expired shared results"""
    sharing_service.cleanup_expired()
    return {"message": "Expired shared results cleaned up"}
