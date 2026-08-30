from fastapi import APIRouter, Depends, HTTPException, status, Request, BackgroundTasks
from typing import List, Optional, Dict, Any, Annotated

from datetime import datetime
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from schemas import QueryRequest, QueryResult, ErrorResponse, ShareRequest, ShareResponse, BatchQueryRequest, BatchQueryResult
from services.database import DatabaseService
from services.llm import LLMService
from services.query import QueryService
from services.sharing import SharingService
from services.billing.billing_service import BillingService
from dependencies import (
    get_db_service, 
    get_llm_service, 
    get_sharing_service, 
    get_billing_service,
    get_mongodb_service,
    get_mem0_service,
    verify_token
)

router = APIRouter(prefix="/queries", tags=["queries"])

def get_query_service(
    db_service: Annotated[DatabaseService, Depends(get_db_service)],
    llm_service: Annotated[LLMService, Depends(get_llm_service)],
    billing_service: Annotated[BillingService, Depends(get_billing_service)],
    mongodb_service: Annotated[Any, Depends(get_mongodb_service)],
    mem0_service: Annotated[Any, Depends(get_mem0_service)]
) -> QueryService:
    """Get a fresh query service instance with current service states"""
    return QueryService(db_service, llm_service, billing_service, mongodb_service, mem0_service)

from fastapi.responses import StreamingResponse

@router.post("/process", response_model=QueryResult, responses={400: {"model": ErrorResponse}})
async def process_natural_language_query(
    query_request: QueryRequest,
    query_service: Annotated[QueryService, Depends(get_query_service)],
    current_user: Annotated[str, Depends(verify_token)],
    background_tasks: BackgroundTasks
) -> Any:
    """Process a natural language query and return SQL results"""
    try:
        result = query_service.process_query(
            user_query=query_request.query,
            max_tokens=query_request.max_tokens,
            temperature=query_request.temperature,
            user_id=current_user,
            session_id=query_request.session_id,
            message_id=query_request.message_id,
            company_id=query_request.company_id,
            background_tasks=background_tasks,
            task_id=query_request.task_id,
            use_chat_history=query_request.use_chat_history,
            history_limit=query_request.history_limit,
            include_explanation=query_request.include_explanation
        )
        return result
        
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except ValueError as e:
        # Handle configuration errors
        if "LLM is not configured" in str(e):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="LLM is not configured. Please configure the LLM using /database/configure-llm endpoint first."
            )
        elif "Database is not connected" in str(e):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Database is not connected. Please connect to a database using /database/connect endpoint first."
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e)
            )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Query processing failed: {str(e)}"
        )

@router.post("/stream")
async def stream_natural_language_query(
    query_request: QueryRequest,
    query_service: Annotated[QueryService, Depends(get_query_service)],
    current_user: Annotated[str, Depends(verify_token)]
):
    """Stream natural language query results chunk by chunk"""
    headers = {
        "Content-Type": "application/x-ndjson",
        "X-Accel-Buffering": "no",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
    }
    return StreamingResponse(
        query_service.stream_query(
            user_query=query_request.query,
            max_tokens=query_request.max_tokens,
            temperature=query_request.temperature,
            user_id=current_user,
            session_id=query_request.session_id,
            message_id=query_request.message_id,
            company_id=query_request.company_id,
            task_id=query_request.task_id,
            use_chat_history=query_request.use_chat_history,
            history_limit=query_request.history_limit,
            include_explanation=query_request.include_explanation
        ),
        headers=headers
    )

@router.post("/process-batch", response_model=BatchQueryResult, responses={400: {"model": ErrorResponse}})
async def process_natural_language_query_batch(
    batch_request: BatchQueryRequest,
    db_service: Annotated[DatabaseService, Depends(get_db_service)],
    llm_service: Annotated[LLMService, Depends(get_llm_service)],
    billing_service: Annotated[BillingService, Depends(get_billing_service)],
    mongodb_service: Annotated[Any, Depends(get_mongodb_service)],
    mem0_service: Annotated[Any, Depends(get_mem0_service)],
    current_user: Annotated[str, Depends(verify_token)],
    background_tasks: BackgroundTasks
):
    try:
        if not db_service.is_connected():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Database is not connected. Please connect to a database using /database/connect endpoint first."
            )

        if not llm_service.is_configured():
            config_details = llm_service.get_config_details()
            detail_msg = "LLM is not configured. Please configure the LLM using /llm/configure endpoint first."
            if config_details:
                detail_msg += f" Current config: {config_details}"
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=detail_msg
            )

        start_time = time.time()

        if batch_request.parallel:
            max_workers = batch_request.max_concurrency or 5
            results: List[QueryResult] = [None] * len(batch_request.queries)

            def run_item(index: int, q):
                item_task_id = q.task_id if q.task_id is not None else batch_request.task_id
                try:
                    service = QueryService(db_service, llm_service, billing_service, mongodb_service, mem0_service)
                    return service.process_query(
                        user_query=q.query, 
                        max_tokens=q.max_tokens, 
                        temperature=q.temperature,
                        user_id=current_user,
                        session_id=q.session_id,
                        message_id=q.message_id,
                        company_id=q.company_id,
                        background_tasks=background_tasks,
                        task_id=item_task_id,
                        use_chat_history=q.use_chat_history,
                        history_limit=q.history_limit,
                        include_explanation=q.include_explanation
                    )
                except Exception as e:
                    # Return a partial failure result instead of crashing
                    return QueryResult(
                        query=q.query,
                        sql_queries=[],
                        results=[],
                        explanation=f"Error processing this query: {str(e)}",
                        timestamp=datetime.now(),
                        execution_time=0.0,
                        input_tokens=0,
                        output_tokens=0,
                        total_tokens=0,
                        user_id=current_user,
                        session_id=q.session_id,
                        message_id=q.message_id,
                        company_id=q.company_id,
                        task_id=item_task_id
                    )

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_map = {
                    executor.submit(run_item, idx, q): idx
                    for idx, q in enumerate(batch_request.queries)
                }
                for future in as_completed(future_map):
                    idx = future_map[future]
                    results[idx] = future.result()
        else:
            query_service = QueryService(db_service, llm_service, billing_service, mongodb_service, mem0_service)
            results: List[QueryResult] = []
            for item in batch_request.queries:
                item_task_id = item.task_id if item.task_id is not None else batch_request.task_id
                try:
                    res = query_service.process_query(
                        user_query=item.query,
                        max_tokens=item.max_tokens,
                        temperature=item.temperature,
                        user_id=current_user,
                        session_id=item.session_id,
                        message_id=item.message_id,
                        company_id=item.company_id,
                        background_tasks=background_tasks,
                        task_id=item_task_id,
                        use_chat_history=item.use_chat_history,
                        history_limit=item.history_limit,
                        include_explanation=item.include_explanation
                    )
                    results.append(res)
                except Exception as e:
                    results.append(QueryResult(
                        query=item.query,
                        sql_queries=[],
                        results=[],
                        explanation=f"Error processing query: {str(e)}",
                        timestamp=datetime.now(),
                        execution_time=0.0,
                        user_id=current_user,
                        session_id=item.session_id,
                        message_id=item.message_id,
                        company_id=item.company_id,
                        task_id=item_task_id
                    ))

        total_time = time.time() - start_time
        return BatchQueryResult(
            results=results,
            timestamp=datetime.now(),
            execution_time=total_time
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Batch query processing failed: {str(e)}"
        )

@router.get("/check-prerequisites", response_model=dict)
async def check_prerequisites(
    db_service: Annotated[DatabaseService, Depends(get_db_service)],
    llm_service: Annotated[LLMService, Depends(get_llm_service)],
    current_user: Annotated[str, Depends(verify_token)]
):
    """Check if all prerequisites are met for query processing"""
    db_connected = db_service.is_connected()
    llm_configured = llm_service.is_configured()
    
    status_msg = "ready" if (db_connected and llm_configured) else "not_ready"
    
    issues = []
    if not db_connected:
        issues.append("Database not connected")
    if not llm_configured:
        issues.append("LLM not configured")
    
    return {
        "status": status_msg,
        "database_connected": db_connected,
        "llm_configured": llm_configured,
        "llm_config": llm_service.get_config_details(),
        "issues": issues,
        "user_identity": current_user,
        "ready_for_queries": db_connected and llm_configured
    }

@router.post("/process-and-share", response_model=dict, responses={400: {"model": ErrorResponse}})
async def process_and_share_query(
    query_request: QueryRequest,
    share_request: ShareRequest,
    request: Request,
    query_service: Annotated[QueryService, Depends(get_query_service)],
    sharing_service: Annotated[SharingService, Depends(get_sharing_service)],
    current_user: Annotated[str, Depends(verify_token)],
    background_tasks: BackgroundTasks
):
    """Process a natural language query and immediately share the result"""
    try:
        # Process the query
        result = query_service.process_query(
            user_query=query_request.query,
            max_tokens=query_request.max_tokens,
            temperature=query_request.temperature,
            user_id=current_user,
            session_id=query_request.session_id,
            background_tasks=background_tasks,
            task_id=query_request.task_id,
            use_chat_history=query_request.use_chat_history,
            history_limit=query_request.history_limit,
            include_explanation=query_request.include_explanation
        )

        # Share the result
        share_id = sharing_service.share_result(result, share_request.expiry_hours)
        
        # Build share URL
        base_url = str(request.base_url).rstrip('/')
        share_url = f"{base_url}/sharing/{share_id}"
        
        # Get the shared data to return expiry time
        shared_data = sharing_service.get_shared_result(share_id)
        
        return {
            "result": result,
            "sharing": {
                "share_id": share_id,
                "share_url": share_url,
                "expires_at": shared_data["expires_at"]
            }
        }
        
    except ValueError as e:
        # Handle configuration errors
        if "LLM is not configured" in str(e):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="LLM is not configured. Please configure the LLM using /database/configure-llm endpoint first."
            )
        elif "Database is not connected" in str(e):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Database is not connected. Please connect to a database using /database/connect endpoint first."
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e)
            )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Query processing and sharing failed: {str(e)}"
        )

@router.get("/history", response_model=List[QueryResult])
async def get_query_history(
    query_service: Annotated[QueryService, Depends(get_query_service)],
    current_user: Annotated[str, Depends(verify_token)],
    limit: int = 10,
    message_id: Optional[str] = None,
    session_id: Optional[str] = None,
    company_id: Optional[str] = None,
    task_id: Optional[int] = None,
    user_id: Optional[str] = None
):
    """Get query history with optional filtering by message_id, session_id, company_id, task_id, or user_id"""
    return query_service.get_history(
        limit=limit,
        message_id=message_id,
        session_id=session_id,
        company_id=company_id,
        task_id=task_id,
        user_id=user_id
    )

@router.get("/history/task/{task_id}", response_model=List[QueryResult])
async def get_query_history_by_task(
    task_id: int,
    query_service: Annotated[QueryService, Depends(get_query_service)],
    current_user: Annotated[str, Depends(verify_token)],
    limit: int = 10
):
    """Get query history filtered by a specific task_id"""
    return query_service.get_history(
        limit=limit,
        task_id=task_id
    )

@router.get("/history/user/{user_id}", response_model=List[QueryResult])
async def get_query_history_by_user(
    user_id: str,
    query_service: Annotated[QueryService, Depends(get_query_service)],
    current_user: Annotated[str, Depends(verify_token)],
    limit: int = 10
):
    """Get query history filtered by a specific user_id"""
    return query_service.get_history(
        limit=limit,
        user_id=user_id
    )

@router.post("/{query_index}/share", response_model=ShareResponse, responses={400: {"model": ErrorResponse}})
async def share_historical_query(
    query_index: int,
    share_request: ShareRequest,
    request: Request,
    query_service: Annotated[QueryService, Depends(get_query_service)],
    sharing_service: Annotated[SharingService, Depends(get_sharing_service)],
    current_user: Annotated[str, Depends(verify_token)]
):
    """Share a query result from history by index"""
    try:
        result = query_service.get_result_by_index(query_index)
        
        share_id = sharing_service.share_result(result, share_request.expiry_hours)
        
        # Build share URL
        base_url = str(request.base_url).rstrip('/')
        share_url = f"{base_url}/sharing/{share_id}"
        
        # Get the shared data to return expiry time
        shared_data = sharing_service.get_shared_result(share_id)
        
        return ShareResponse(
            share_id=share_id,
            share_url=share_url,
            expires_at=shared_data["expires_at"]
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to share historical query: {str(e)}"
        )

@router.delete("/history", response_model=dict)
async def clear_query_history(
    query_service: Annotated[QueryService, Depends(get_query_service)],
    current_user: Annotated[str, Depends(verify_token)]
):
    """Clear query history"""
    query_service.clear_history()
    return {"message": "Query history cleared"}