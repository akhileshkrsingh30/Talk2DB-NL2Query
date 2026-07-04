from fastapi import APIRouter, Depends, HTTPException, status
from typing import Annotated, Optional, Dict, Any, List
from pydantic import BaseModel, Field
import json
import logging
from dependencies import verify_token, get_mem0_service
from services.mem0_service import Mem0Service
from schemas import MemoriesRequest, ErrorResponse

router = APIRouter(prefix="/memories", tags=["memories"])

def delete_task_points_from_db(task_id: str, mem0_service: Mem0Service) -> int:
    """
    Deletes any existing memory entries matching task_id
    using direct Qdrant client to scroll all points, filtering in Python,
    and deleting matching points by ID.
    Returns the count of deleted items.
    """
    from config import settings
    from qdrant_client.models import PointIdsList
    import json
    deleted_count = 0
    
    print(f"\n[DEBUG] Starting delete_task_points_from_db for task_id: {task_id}")

    provider = settings.mem0_vector_store_provider.lower()
    if provider == "qdrant":
        try:
            # Access the raw qdrant client from mem0 vector store
            qdrant_client = mem0_service.client.vector_store.client
            collection_name = settings.mem0_collection_name
            
            # Scroll all points from the collection without filter to avoid index requirement
            print(f"[DEBUG] Scrolling Qdrant collection '{collection_name}' to find points with task_id...")
            offset = None
            points_to_delete = []
            
            while True:
                scroll_res = qdrant_client.scroll(
                    collection_name=collection_name,
                    limit=100,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False
                )
                points, next_offset = scroll_res
                
                for p in points:
                    payload = p.payload or {}
                    
                    # Check both flat payload and nested metadata payload
                    meta = payload.get("metadata") or payload
                    if isinstance(meta, str):
                        try:
                            meta = json.loads(meta)
                        except Exception:
                            meta = payload
                            
                    # Retrieve task_id from either the payload or the metadata dictionary
                    m_task_id = payload.get("task_id") or meta.get("task_id")
                    
                    if m_task_id is not None and str(m_task_id) == str(task_id):
                        points_to_delete.append(p.id)
                        print(f"[DEBUG] Found point to delete: ID={p.id}, Payload={payload}")
                        
                offset = next_offset
                if not offset or len(points) < 100:
                    break
                    
            if points_to_delete:
                print(f"[DEBUG] Deleting {len(points_to_delete)} points from Qdrant: {points_to_delete}")
                qdrant_client.delete(
                    collection_name=collection_name,
                    points_selector=PointIdsList(points=points_to_delete)
                )
                deleted_count = len(points_to_delete)
                print("[DEBUG] Delete call completed.")
            else:
                print("[DEBUG] No points matched task_id in Qdrant scroll.")
        except Exception as e:
            print(f"[DEBUG] Qdrant direct scroll-delete failed: {str(e)}")
            
    # 2. Universal Mem0 delete loop fallback (as a backup)
    try:
        memories = mem0_service.client.get_all(filters={"user_id": "global"}, top_k=100)
        print(f"[DEBUG] Fallback: Found {len(memories)} total memories with user_id='global' via SDK.")
        for m in memories:
            meta = m.get("metadata") if isinstance(m, dict) else getattr(m, "metadata", None)
            
            # Safely handle serialized JSON string metadata
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    pass
                    
            if meta and isinstance(meta, dict):
                m_task_id = meta.get("task_id")
                if str(m_task_id) == str(task_id):
                    memory_id = m.get("id") if isinstance(m, dict) else getattr(m, "id", None)
                    if memory_id:
                        try:
                            print(f"[DEBUG] Fallback delete for memory ID: {memory_id} via SDK...")
                            mem0_service.client.delete(memory_id)
                            deleted_count += 1
                        except Exception as delete_err:
                            pass
    except Exception as e:
        print(f"[DEBUG] Fallback delete failed: {str(e)}")
        
    print(f"[DEBUG] Finished delete_task_points_from_db. Deleted count: {deleted_count}\n")
    return deleted_count

@router.post("", status_code=status.HTTP_201_CREATED, responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
async def store_task_memory(
    request: MemoriesRequest,
    mem0_service: Annotated[Mem0Service, Depends(get_mem0_service)],
    current_user: Annotated[str, Depends(verify_token)]
):
    """
    Store task-to-table mappings in the pgvector-backed Mem0 memory.
    """
    if not mem0_service.is_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, 
            detail="Mem0 service is not initialized or disabled."
        )
        
    try:
        # Delete any existing memory entries for this task_id to ensure uniqueness
        delete_task_points_from_db(request.task_id, mem0_service)

        content = f"Task '{request.task_id}' requires tables: {', '.join(request.tables)}."
        metadata = {
            "type": "task_tables",
            "task_id": request.task_id,
            "tables": json.dumps(request.tables)
        }

        # Store in Mem0 using user_id="global" with infer=False to prevent LLM fact-extraction duplicates
        result = mem0_service.client.add(
            content,
            user_id="global",
            metadata=metadata,
            infer=False
        )
        
        # Invalidate the cache to ensure updates are fetched
        mem0_service.invalidate_cache()
        
        return {
            "status": "success",
            "message": f"Successfully pushed task '{request.task_id}' memory to Mem0",
            "result": result
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to store memory: {str(e)}"
        )

class MemorySearchRequest(BaseModel):
    query: str = Field(..., description="Natural language query to search memories")
    user_id: Optional[str] = Field(None, description="Optional user ID filter")
    agent_id: Optional[str] = Field(None, description="Optional agent ID filter")
    limit: Optional[int] = Field(5, description="Maximum number of results to return")

@router.post("/search", responses={500: {"model": ErrorResponse}})
async def search_memories(
    request: MemorySearchRequest,
    mem0_service: Annotated[Mem0Service, Depends(get_mem0_service)],
    current_user: Annotated[str, Depends(verify_token)]
):
    """
    Search memories using natural language (semantic similarity search).
    """
    if not mem0_service.is_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, 
            detail="Mem0 service is not initialized or disabled."
        )
    try:
        # Construct search parameters
        search_params = {
            "query": request.query,
            "limit": request.limit or 5
        }
        
        # In Mem0, search can filter by user_id or agent_id
        if request.user_id:
            search_params["user_id"] = request.user_id
        if request.agent_id:
            search_params["agent_id"] = request.agent_id
            
        try:
            mems = mem0_service.client.search(**search_params)
        except Exception:
            # Try with filters dictionary as fallback for newer Mem0 versions
            filters = {}
            if request.user_id:
                filters["user_id"] = request.user_id
            if request.agent_id:
                filters["agent_id"] = request.agent_id
            mems = mem0_service.client.search(query=request.query, filters=filters, limit=request.limit or 5)
        
        results = []
        for m in mems:
            results.append({
                "id": m.get("id") if isinstance(m, dict) else getattr(m, "id", None),
                "memory": m.get("memory") if isinstance(m, dict) else getattr(m, "memory", ""),
                "score": m.get("score") if isinstance(m, dict) else getattr(m, "score", None),
                "metadata": m.get("metadata") if isinstance(m, dict) else getattr(m, "metadata", {})
            })
            
        return {"status": "success", "query": request.query, "results": results}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to search memories: {str(e)}"
        )

@router.get("/all", responses={500: {"model": ErrorResponse}})
async def get_all_mem0_data(
    mem0_service: Annotated[Mem0Service, Depends(get_mem0_service)],
    current_user: Annotated[str, Depends(verify_token)]
):
    """
    Fetch all raw data stored in Mem0 pgvector database.
    """
    if not mem0_service.is_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, 
            detail="Mem0 service is not initialized or disabled."
        )
    try:
        from config import settings
        from datetime import datetime, date
        import requests
        
        provider = settings.mem0_vector_store_provider.lower()
        if provider == "qdrant":
            # Use Qdrant REST scroll to fetch all points in collection
            url = settings.mem0_qdrant_url
            if not url:
                url = f"http://{settings.mem0_qdrant_host}:{settings.mem0_qdrant_port}"
            
            headers = {}
            if settings.mem0_qdrant_api_key:
                headers["api-key"] = settings.mem0_qdrant_api_key
                
            scroll_url = f"{url}/collections/{settings.mem0_collection_name}/points/scroll"
            response = requests.post(
                scroll_url,
                json={"limit": 1000, "with_payload": True, "with_vector": False},
                headers=headers,
                timeout=5
            )
            
            if response.status_code == 200:
                points = response.json().get("result", {}).get("points", [])
                results = []
                for pt in points:
                    payload = pt.get("payload", {})
                    meta = payload.get("metadata") or {}
                    if isinstance(meta, str):
                        try:
                            meta = json.loads(meta)
                        except Exception:
                            pass
                    results.append({
                        "id": pt.get("id"),
                        "memory": payload.get("memory") or payload.get("text") or "",
                        "user_id": payload.get("user_id"),
                        "agent_id": payload.get("agent_id"),
                        "metadata": meta,
                        "created_at": payload.get("created_at") or payload.get("data", {}).get("created_at")
                    })
                return {"status": "success", "source": "qdrant_rest", "count": len(results), "data": results}
            else:
                logging.warning(f"Qdrant scroll API returned {response.status_code}: {response.text}")
                # Fall back to get_all client queries
                raise RuntimeError("Qdrant REST call failed")
                
        import psycopg2
        from psycopg2.extras import RealDictCursor
        
        # Connect to the pgvector database directly to dump everything
        conn = psycopg2.connect(settings.mem0_pg_connection_string)
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        table_name = settings.mem0_collection_name
        
        # Verify if the table exists
        cursor.execute(
            "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = %s)",
            (table_name,)
        )
        exists = cursor.fetchone()["exists"]
        
        if not exists:
            # Fall back to Mem0 client get_all for common keys
            results = []
            uids = ["global", settings.auth_default_user]
            try:
                from services.registry import service_registry
                db_service = service_registry.get_db_service()
                if db_service and db_service.is_connected():
                    user_rows = db_service.execute_query("SELECT Email FROM AppUsers WHERE IsActive = 1")
                    if user_rows and isinstance(user_rows, list):
                        for row in user_rows:
                            email = row.get("Email")
                            if email and email not in uids:
                                uids.append(email)
            except Exception as db_err:
                logging.warning(f"Failed to fetch user emails from DB: {db_err}")
                
            for uid in uids:
                try:
                    mems = mem0_service.client.get_all(filters={"user_id": uid})
                    results.extend(mems)
                except Exception:
                    pass
            try:
                mems = mem0_service.client.get_all(filters={"agent_id": "global_rbac"})
                results.extend(mems)
            except Exception:
                pass
            return {"status": "success", "source": "mem0_client_fallback", "data": results}
            
        # Get actual column names from the pgvector table dynamically
        cursor.execute(
            """
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = %s
            """,
            (table_name,)
        )
        columns_info = cursor.fetchall()
        
        valid_cols = []
        for col in columns_info:
            col_name = col["column_name"]
            data_type = col["data_type"]
            # Skip any vector/embedding columns
            if "vector" in data_type.lower() or "embedding" in col_name.lower():
                continue
            valid_cols.append(col_name)
            
        if not valid_cols:
            valid_cols = ["id", "metadata", "user_id", "created_at"]
            
        cols_str = ", ".join(valid_cols)
        cursor.execute(f"SELECT {cols_str} FROM {table_name}")
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        
        # Parse metadata json if stored as string
        for row in rows:
            if isinstance(row.get("metadata"), str):
                try:
                    row["metadata"] = json.loads(row["metadata"])
                except Exception:
                    pass
            if isinstance(row.get("created_at"), (datetime, date)):
                row["created_at"] = row["created_at"].isoformat()
                
        return {"status": "success", "source": "pgvector_direct", "count": len(rows), "data": rows}
        
    except Exception as e:
        # Fallback to client get_all if direct DB fails
        try:
            results = []
            uids = ["global", settings.auth_default_user]
            try:
                from services.registry import service_registry
                db_service = service_registry.get_db_service()
                if db_service and db_service.is_connected():
                    user_rows = db_service.execute_query("SELECT Email FROM AppUsers WHERE IsActive = 1")
                    if user_rows and isinstance(user_rows, list):
                        for row in user_rows:
                            email = row.get("Email")
                            if email and email not in uids:
                                uids.append(email)
            except Exception as db_err:
                logging.warning(f"Failed to fetch user emails from DB in exception handler: {db_err}")
                
            for uid in uids:
                mems = mem0_service.client.get_all(filters={"user_id": uid})
                results.extend(mems)
            mems = mem0_service.client.get_all(filters={"agent_id": "global_rbac"})
            results.extend(mems)
            return {"status": "success", "source": "fallback", "data": results}
        except Exception as fallback_err:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to fetch memories: {str(e)} | Fallback error: {str(fallback_err)}"
            )

@router.get("", responses={500: {"model": ErrorResponse}})
async def list_task_memories(
    mem0_service: Annotated[Mem0Service, Depends(get_mem0_service)],
    current_user: Annotated[str, Depends(verify_token)],
    task_id: Optional[str] = None
):
    """
    Retrieve stored task memories. Optionally filter by task_id.
    """
    if not mem0_service.is_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, 
            detail="Mem0 service is not initialized or disabled."
        )
        
    try:
        memories = mem0_service.client.get_all(filters={"user_id": "global"})
        results = []
        for m in memories:
            meta = {}
            if isinstance(m, dict):
                meta = m.get("metadata") or {}
            elif hasattr(m, "metadata"):
                meta = getattr(m, "metadata") or {}
                
            if meta and meta.get("type") == "task_tables":
                m_task_id = meta.get("task_id")
                if task_id and m_task_id != task_id:
                    continue
                
                raw_tables = meta.get("tables", "[]")
                try:
                    tables = json.loads(raw_tables) if isinstance(raw_tables, str) else raw_tables
                except Exception:
                    tables = []
                
                results.append({
                    "id": m.get("id") if isinstance(m, dict) else getattr(m, "id", None),
                    "task_id": m_task_id,
                    "tables": tables,
                    "memory": m.get("memory") if isinstance(m, dict) else getattr(m, "memory", "")
                })
        return {"status": "success", "memories": results}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve memories: {str(e)}"
        )

class MemoryUpdateRequest(BaseModel):
    tables: List[str] = Field(..., description="Updated list of tables associated with the task")

@router.put("/{task_id}", status_code=status.HTTP_200_OK, responses={500: {"model": ErrorResponse}})
async def update_task_memory(
    task_id: str,
    request: MemoryUpdateRequest,
    mem0_service: Annotated[Mem0Service, Depends(get_mem0_service)],
    current_user: Annotated[str, Depends(verify_token)]
):
    """
    Update task-to-table mapping for a given task_id in Mem0.
    """
    if not mem0_service.is_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, 
            detail="Mem0 service is not initialized or disabled."
        )
    try:
        # First, find and delete existing mappings for this task_id
        delete_task_points_from_db(task_id, mem0_service)

        # Add the updated mapping
        content = f"Task '{task_id}' requires tables: {', '.join(request.tables)}."
        metadata = {
            "type": "task_tables",
            "task_id": task_id,
            "tables": json.dumps(request.tables)
        }

        result = mem0_service.client.add(
            content,
            user_id="global",
            metadata=metadata,
            infer=False
        )
        
        mem0_service.invalidate_cache()
        return {
            "status": "success",
            "message": f"Successfully updated memory for task_id '{task_id}'.",
            "result": result
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update memory: {str(e)}"
        )

@router.delete("/{task_id}", status_code=status.HTTP_200_OK, responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
async def delete_task_memory(
    task_id: str,
    mem0_service: Annotated[Mem0Service, Depends(get_mem0_service)],
    current_user: Annotated[str, Depends(verify_token)]
):
    """
    Delete task-to-table mapping for a given task_id from Mem0.
    """
    if not mem0_service.is_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, 
            detail="Mem0 service is not initialized or disabled."
        )
    try:
        # Find and delete memories matching the task_id
        deleted_count = delete_task_points_from_db(task_id, mem0_service)
                    
        if deleted_count == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No memory entry found for task_id '{task_id}'."
            )
            
        mem0_service.invalidate_cache()
        return {
            "status": "success", 
            "message": f"Successfully deleted {deleted_count} memory entries for task_id '{task_id}'."
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete memory: {str(e)}"
        )
