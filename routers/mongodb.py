from fastapi import APIRouter, Depends, HTTPException, status
from typing import Annotated, Any
from datetime import datetime
import time
import json
import re
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from schemas import (
    MongoDBConnection, 
    MongoDBSelect, 
    MongoDBCollectionSelect,
    MongoDBConnectionResponse, 
    MongoDBDatabaseList,
    MongoDBCollectionList,
    MongoDBQueryRequest,
    MongoDBQueryResult,
    ErrorResponse
)
from services.mongodb import MongoDBService
from services.llm import LLMService
from dependencies import verify_token, get_llm_service
from services.registry import service_registry

router = APIRouter(prefix="/mongodb", tags=["mongodb"])

def get_mongodb_service() -> MongoDBService:
    """Dependency to get MongoDB service instance"""
    return service_registry.get_mongodb_service()

@router.post("/connect", response_model=MongoDBConnectionResponse, responses={400: {"model": ErrorResponse}})
async def connect_to_mongodb(
    connection: MongoDBConnection,
    mongodb_service: Annotated[MongoDBService, Depends(get_mongodb_service)],
    current_user: Annotated[str, Depends(verify_token)]
):
    """Connect to a MongoDB server"""
    try:
        # Log the incoming connection request (without password)
        print(f"MongoDB connection request - Host: {connection.host}, Port: {connection.port}, "
              f"Database: {connection.database}, Username: {connection.username}")
        
        connection_params = {
            "host": connection.host,
            "port": connection.port,
            "database": connection.database,
            "username": connection.username,
            "password": connection.password,
            "auth_source": connection.auth_source,
            "auth_mechanism": connection.auth_mechanism
        }
        
        success = mongodb_service.connect(connection_params)
        
        if success:
            server_info = mongodb_service.get_server_info()
            params = mongodb_service.get_connection_params()
            
            return MongoDBConnectionResponse(
                status="success",
                message="Connected to MongoDB successfully",
                server_info=server_info,
                details={
                    "host": connection.host,
                    "port": connection.port,
                    "database": params.get("database", "admin"),
                    "username": connection.username or "none"
                }
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to connect to MongoDB"
            )
            
    except ValueError as e:
        # Validation errors (missing fields, invalid port, etc.)
        print(f"Validation error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Validation error: {str(e)}"
        )
    except ConnectionError as e:
        # MongoDB connection errors
        print(f"Connection error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Connection error: {str(e)}"
        )
    except Exception as e:
        # Other unexpected errors
        print(f"Unexpected error during MongoDB connection: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error: {str(e)}"
        )

@router.post("/disconnect", response_model=dict)
async def disconnect_mongodb(
    mongodb_service: Annotated[MongoDBService, Depends(get_mongodb_service)],
    current_user: Annotated[str, Depends(verify_token)]
):
    """Disconnect from MongoDB"""
    mongodb_service.disconnect()
    return {"message": "Disconnected from MongoDB"}

@router.get("/list", response_model=MongoDBDatabaseList)
async def list_databases(
    mongodb_service: Annotated[MongoDBService, Depends(get_mongodb_service)],
    current_user: Annotated[str, Depends(verify_token)]
):
    """List all databases available on the MongoDB server"""
    try:
        # Check if connected first
        if not mongodb_service.is_connected():
            print("Error: Attempted to list MongoDB databases without being connected")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="MongoDB not connected. Please connect first using /mongodb/connect endpoint (you can omit the 'database' field to connect to the default 'admin' database)."
            )
        
        databases = mongodb_service.get_databases()
        print(f"Successfully listed {len(databases)} MongoDB databases")
        return MongoDBDatabaseList(
            status="success",
            databases=databases,
            count=len(databases)
        )
    except HTTPException:
        raise
    except RuntimeError as e:
        print(f"Runtime error listing MongoDB databases: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        print(f"Unexpected error listing MongoDB databases: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list databases: {str(e)}"
        )

@router.post("/select", response_model=MongoDBConnectionResponse)
async def select_database(
    selection: MongoDBSelect,
    mongodb_service: Annotated[MongoDBService, Depends(get_mongodb_service)],
    current_user: Annotated[str, Depends(verify_token)]
):
    """Switch to a specific database after listing them"""
    try:
        success = mongodb_service.select_database(selection.database)
        if success:
            params = mongodb_service.get_connection_params()
            return MongoDBConnectionResponse(
                status="success",
                message=f"Switched to database '{selection.database}' successfully",
                details={
                    "host": params.get("host"),
                    "port": params.get("port"),
                    "database": selection.database,
                    "username": params.get("username", "none")
                }
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to switch to database '{selection.database}'"
            )
    except RuntimeError as e:
        print(f"Runtime error selecting database: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        print(f"Unexpected error selecting database: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error: {str(e)}"
        )

@router.get("/collections", response_model=MongoDBCollectionList)
async def list_collections(
    mongodb_service: Annotated[MongoDBService, Depends(get_mongodb_service)],
    current_user: Annotated[str, Depends(verify_token)]
):
    """List all collections in the current database"""
    try:
        # Check if connected first
        if not mongodb_service.is_connected():
            print("Error: Attempted to list MongoDB collections without being connected")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="MongoDB not connected. Please connect first using /mongodb/connect endpoint."
            )
        
        collections = mongodb_service.get_collections()
        current_db = mongodb_service.current_database or "unknown"
        print(f"Successfully listed {len(collections)} collections in database '{current_db}'")
        
        return MongoDBCollectionList(
            status="success",
            collections=collections,
            count=len(collections),
            database=current_db
        )
    except HTTPException:
        raise
    except RuntimeError as e:
        print(f"Runtime error listing collections: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        print(f"Unexpected error listing collections: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list collections: {str(e)}"
        )

@router.post("/select-collection", response_model=dict)
async def select_collection(
    selection: MongoDBCollectionSelect,
    mongodb_service: Annotated[MongoDBService, Depends(get_mongodb_service)],
    current_user: Annotated[str, Depends(verify_token)]
):
    """Switch to a specific collection"""
    try:
        success = mongodb_service.select_collection(selection.collection)
        if success:
            return {
                "status": "success",
                "message": f"Switched to collection '{selection.collection}' successfully",
                "database": mongodb_service.current_database,
                "collection": selection.collection
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to switch to collection '{selection.collection}'"
            )
    except RuntimeError as e:
        print(f"Runtime error selecting collection: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        print(f"Unexpected error selecting collection: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error: {str(e)}"
        )

@router.get("/status", response_model=MongoDBConnectionResponse)
async def get_mongodb_status(
    mongodb_service: Annotated[MongoDBService, Depends(get_mongodb_service)],
    current_user: Annotated[str, Depends(verify_token)]
):
    """Get current MongoDB connection status"""
    if mongodb_service.is_connected():
        params = mongodb_service.get_connection_params()
        server_info = mongodb_service.get_server_info()
        
        return MongoDBConnectionResponse(
            status="connected",
            message="MongoDB is connected",
            server_info=server_info,
            details={
                "host": params.get("host"),
                "port": params.get("port"),
                "database": mongodb_service.current_database or "none",
                "collection": mongodb_service.current_collection or "none",
                "username": params.get("username", "none")
            } if params else None
        )
    else:
        return MongoDBConnectionResponse(
            status="disconnected",
            message="MongoDB is not connected"
        )

@router.get("/schema", response_model=dict)
async def get_collection_schema(
    mongodb_service: Annotated[MongoDBService, Depends(get_mongodb_service)],
    current_user: Annotated[str, Depends(verify_token)]
):
    """Get the inferred schema of the currently selected collection"""
    try:
        if not mongodb_service.is_connected():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="MongoDB not connected"
            )
        if not mongodb_service.current_collection:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No collection selected. Use /mongodb/select-collection first."
            )
        
        schema = mongodb_service.get_collection_schema()
        return {"status": "success", "schema": schema}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get schema: {str(e)}"
        )

@router.post("/process", response_model=MongoDBQueryResult, responses={400: {"model": ErrorResponse}})
async def process_mongodb_query(
    query_request: MongoDBQueryRequest,
    mongodb_service: Annotated[MongoDBService, Depends(get_mongodb_service)],
    llm_service: Annotated[LLMService, Depends(get_llm_service)],
    current_user: Annotated[str, Depends(verify_token)]
):
    """Process a natural language query against the selected MongoDB collection"""
    try:
        start_time = time.time()
        
        # Validate prerequisites
        if not mongodb_service.is_connected():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="MongoDB not connected. Please connect first using /mongodb/connect."
            )
        if not mongodb_service.current_collection:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No collection selected. Use /mongodb/select-collection first."
            )
        if not llm_service.is_configured():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="LLM is not configured. Please configure the LLM using /database/configure-llm endpoint first."
            )
        
        print(f"Processing MongoDB query: {query_request.query[:100]}...")
        
        # Get collection schema for the LLM
        schema_description = mongodb_service.get_schema_description()
        print(f"✓ Got collection schema: {len(schema_description)} characters")
        
        # Use tiktoken to count tokens
        try:
            import tiktoken
            encoding = tiktoken.get_encoding("cl100k_base")
            count_tokens = lambda text: len(encoding.encode(text)) if text else 0
        except Exception:
            count_tokens = lambda text: len(text.split()) if text else 0
        
        input_tokens = count_tokens(query_request.query) + count_tokens(schema_description)
        
        # Configure LLM with request parameters
        configurable_llm = llm_service.llm.bind(
            max_completion_tokens=query_request.max_tokens or 1024,
            temperature=query_request.temperature or 0.0
        )
        
        # Generate MongoDB query using LLM
        prompt = ChatPromptTemplate.from_template(
            """You are a MongoDB expert. Generate a valid MongoDB query for the following question.
            The query will be used with PyMongo's find() method.

            Collection Schema (sample document fields):
            {schema_info}

            Question: {Question}

            CRITICAL RULES:
            - Return ONLY a valid JSON object with two keys: "filter" and "projection"
            - "filter" is the MongoDB query filter (the first argument to find())
            - "projection" is the fields to return (the second argument to find()). Use 1 to include, 0 to exclude. Always exclude "_id" unless specifically asked.
            - Use ONLY the exact field names from the schema above
            - For geospatial queries, use native MongoDB operators like $near, $nearSphere, $geoWithin, or $geoIntersects if the schema contains 2dsphere indexes or coordinates. 
            - If calculating distance manually via $expr, keep the formula as concise as possible to avoid truncation.
            - For string matching, use $regex with $options: "i" for case-insensitive
            - For numeric comparisons use $gt, $gte, $lt, $lte, $eq, $ne
            - For sorting, add a "sort" key with field and direction (1=asc, -1=desc)
            - For limiting results, add a "limit" key with an integer value
            - Do NOT wrap the JSON in markdown code blocks or backticks
            - Return ONLY the raw JSON object, nothing else
            - ENSURE the JSON is complete and valid.

            Example output:
            {{"filter": {{"age": {{"$gt": 25}}}}, "projection": {{"name": 1, "age": 1, "_id": 0}}, "sort": {{"age": -1}}, "limit": 10}}
            """
        )
        
        mongo_chain = prompt | configurable_llm | StrOutputParser()
        
        generated_text = mongo_chain.invoke({
            "Question": query_request.query,
            "schema_info": schema_description
        })
        print(f"✓ LLM generated: {generated_text[:300]}...")
        
        output_tokens = count_tokens(str(generated_text))
        
        # Parse the generated MongoDB query
        # Clean up LLM output - strip markdown code blocks if present
        cleaned_text = generated_text.strip()
        cleaned_text = re.sub(r'^```(?:json)?\s*', '', cleaned_text)
        cleaned_text = re.sub(r'\s*```$', '', cleaned_text)
        cleaned_text = cleaned_text.strip()
        
        try:
            query_dict = json.loads(cleaned_text)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM generated invalid JSON. Raw output: {generated_text[:500]}. Error: {str(e)}")
        
        print(f"✓ Parsed MongoDB query: {json.dumps(query_dict, indent=2)[:200]}")
        
        # Execute the query
        results = mongodb_service.execute_query(query_dict)
        print(f"✓ Query returned {len(results)} results")
        
        # Generate explanation
        explanation_chain = llm_service.create_mongodb_explanation_chain()
        
        # Limit results sent to LLM for explanation to avoid token overflow
        results_for_explanation = results[:20] if len(results) > 20 else results
        
        input_tokens += count_tokens(query_request.query) + count_tokens(schema_description)
        
        explanation = explanation_chain.invoke({
            "Question": query_request.query,
            "schema_info": schema_description,
            "results": str(results_for_explanation)
        })
        
        output_tokens += count_tokens(str(explanation))
        print("✓ Generated explanation")
        
        execution_time = time.time() - start_time
        
        response = MongoDBQueryResult(
            query=query_request.query,
            mongo_query=query_dict,
            results=results,
            result_count=len(results),
            explanation=explanation,
            collection=mongodb_service.current_collection,
            database=mongodb_service.current_database,
            timestamp=datetime.now(),
            execution_time=execution_time,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            user_id=current_user,
            session_id=query_request.session_id
        )
        
        print(f"[INFO] MongoDB query processed in {execution_time:.2f}s | Results: {len(results)} | Tokens: In={input_tokens}, Out={output_tokens}")
        return response
        
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        print(f"✗ MongoDB query processing failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"MongoDB query processing failed: {str(e)}"
        )
