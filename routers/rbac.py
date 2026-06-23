from fastapi import APIRouter, Depends, HTTPException, status
from typing import Dict, Any, List, Annotated
from dependencies import verify_token, get_mem0_service
from services.mem0_service import Mem0Service
from schemas import UserPolicyRequest, UserPolicyRawRequest, UserPolicyResponse, ErrorResponse, MemoryStoreRequest

router = APIRouter(prefix="/rbac", tags=["rbac"])

@router.post("/user/policy", status_code=status.HTTP_201_CREATED, responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
async def create_user_policy(
    request: UserPolicyRequest,
    mem0_service: Annotated[Mem0Service, Depends(get_mem0_service)],
    current_user: Annotated[str, Depends(verify_token)]
):
    """
    Store formatted security guidelines in Mem0 memory for a specific user.
    Example guidelines:
    - User role is standard.
    - User belongs to the Sales department.
    - Restrict access to tables: salaries, payroll.
    """
    if not mem0_service.is_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, 
            detail="Mem0 service is not initialized or disabled."
        )
        
    username = request.username
    policies = [
        f"User role is {request.role}.",
        f"User belongs to the {request.department} department."
    ]
    if request.restricted_tables:
        tables_str = ", ".join(request.restricted_tables)
        policies.append(f"Restrict access to tables: {tables_str}")
        
    try:
        for policy in policies:
            mem0_service.client.add(policy, user_id=username)
        return {"status": "success", "message": f"Security policies set for user {username}"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to store policy in Mem0: {str(e)}"
        )

@router.post("/user/policy/raw", status_code=status.HTTP_201_CREATED, responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
async def create_user_policy_raw(
    request: UserPolicyRawRequest,
    mem0_service: Annotated[Mem0Service, Depends(get_mem0_service)],
    current_user: Annotated[str, Depends(verify_token)]
):
    """
    Store custom/raw natural language security constraints in Mem0.
    Can be scoped to a single user (using username) or globally (using agent_id='global_rbac').
    """
    if not mem0_service.is_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, 
            detail="Mem0 service is not initialized or disabled."
        )
        
    if not request.username and not request.agent_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either username or agent_id must be provided."
        )
        
    try:
        kwargs = {}
        if request.username:
            kwargs["user_id"] = request.username
        if request.agent_id:
            kwargs["agent_id"] = request.agent_id


        mem0_service.client.add(request.memory, **kwargs)
        target = request.username if request.username else f"Agent: {request.agent_id}"
        return {"status": "success", "message": f"Raw policy added to Mem0 for {target}"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to store raw policy: {str(e)}"
        )

@router.get("/user/policy", response_model=UserPolicyResponse, responses={500: {"model": ErrorResponse}})
async def get_user_policy(
    username: str, 
    mem0_service: Annotated[Mem0Service, Depends(get_mem0_service)],
    current_user: Annotated[str, Depends(verify_token)]
):
    """
    Retrieve and parse active resolved permissions for a user from Mem0.
    """
    if not mem0_service.is_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, 
            detail="Mem0 service is not initialized or disabled."
        )
        
    try:
        permissions = mem0_service.get_user_permissions(username)
        return UserPolicyResponse(username=username, resolved_permissions=permissions)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve user policy: {str(e)}"
        )

@router.delete("/reset", status_code=status.HTTP_200_OK, responses={500: {"model": ErrorResponse}})
async def reset_memories(
    mem0_service: Annotated[Mem0Service, Depends(get_mem0_service)],
    current_user: Annotated[str, Depends(verify_token)]
):
    """
    Reset all memories inside Mem0 (Chroma/pgvector).
    """
    if not mem0_service.is_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, 
            detail="Mem0 service is not initialized or disabled."
        )
        
    try:
        if hasattr(mem0_service.client, "reset"):
            mem0_service.client.reset()
        elif hasattr(mem0_service.client, "reset_all"):
            mem0_service.client.reset_all()
        else:
            raise NotImplementedError("Reset not supported directly by the underlying client.")
            
        return {"status": "success", "message": "All Mem0 memories reset successfully."}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reset Memories: {str(e)}"
        )

@router.post("/memory", status_code=status.HTTP_201_CREATED, responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
async def store_memory(
    request: MemoryStoreRequest,
    mem0_service: Annotated[Mem0Service, Depends(get_mem0_service)],
    current_user: Annotated[str, Depends(verify_token)]
):
    """
    Store arbitrary text/data in the pgvector-backed Mem0 memory.
    """
    if not mem0_service.is_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, 
            detail="Mem0 service is not initialized or disabled."
        )
        
    try:
        kwargs = {}
        if request.user_id:
            kwargs["user_id"] = request.user_id
        if request.agent_id:
            kwargs["agent_id"] = request.agent_id
        if request.metadata:
            kwargs["metadata"] = request.metadata

        result = mem0_service.client.add(request.content, **kwargs)
        return {
            "status": "success",
            "message": "Data successfully stored in pgvector memory",
            "result": result
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to store memory: {str(e)}"
        )
