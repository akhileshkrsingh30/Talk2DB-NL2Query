from pymongo import MongoClient
from datetime import datetime
from typing import Dict, Any, List, Optional
from copy import deepcopy
from config import settings

class MongoDBService:
    def __init__(self):
        self.client = None
        self.db = None
        self.collection = None
        self.connection_params: Optional[Dict[str, Any]] = None
        self.connected = False
        self.current_database = None
        self.current_collection = None
        
        # Try to auto-connect from environment variables (backward compatibility)
        if settings.mongo_uri and settings.mongo_db_name:
            try:
                self._legacy_connect()
            except Exception as e:
                print(f"Auto-connect to MongoDB failed: {e}")

    def _legacy_connect(self):
        """Legacy auto-connect method for backward compatibility"""
        try:
            self.client = MongoClient(settings.mongo_uri)
            self.db = self.client[settings.mongo_db_name]
            self.collection = self.db["query_results"]
            self.current_database = settings.mongo_db_name
            self.current_collection = "query_results"
            self.connected = True
            print(f"Auto-connected to MongoDB: {settings.mongo_uri} (database: {settings.mongo_db_name})")
        except Exception as e:
            print(f"Failed to auto-connect to MongoDB: {e}")
            self.client = None
            self.connected = False

    def connect(self, connection_params: Dict[str, Any]) -> bool:
        """Establish MongoDB connection with dynamic parameters"""
        try:
            # Validate required parameters
            required_fields = ["host", "port"]
            missing_fields = []
            
            for field in required_fields:
                value = connection_params.get(field)
                if value is None or (isinstance(value, str) and not value.strip()):
                    missing_fields.append(field)
            
            if missing_fields:
                raise ValueError(f"Required connection fields missing or empty: {', '.join(missing_fields)}")
            
            # Validate port is numeric
            port_value = str(connection_params["port"]).strip()
            if not port_value.isdigit():
                raise ValueError(f"Port must be a number, got: {port_value}")
            
            # Build connection URI
            host = connection_params["host"]
            port = int(port_value)
            username = connection_params.get("username")
            password = connection_params.get("password")
            auth_source = connection_params.get("auth_source", "admin")
            auth_mechanism = connection_params.get("auth_mechanism")
            
            # Construct MongoDB URI
            if username and password:
                # URL encode username and password
                from urllib.parse import quote_plus
                username_encoded = quote_plus(username)
                password_encoded = quote_plus(password)
                
                if auth_mechanism:
                    uri = f"mongodb://{username_encoded}:{password_encoded}@{host}:{port}/?authSource={auth_source}&authMechanism={auth_mechanism}"
                else:
                    uri = f"mongodb://{username_encoded}:{password_encoded}@{host}:{port}/?authSource={auth_source}"
            else:
                uri = f"mongodb://{host}:{port}/"
            
            print(f"Connecting to MongoDB: {host}:{port}")
            
            # Create client and test connection
            client = MongoClient(uri, serverSelectionTimeoutMS=5000)
            client.admin.command('ping')  # Test connection
            
            # Get database (default to 'admin' if not specified)
            db_name = connection_params.get("database")
            if not db_name or (isinstance(db_name, str) and not db_name.strip()):
                db_name = "admin"
                print(f"No database specified, defaulting to 'admin'")
            
            # Store connection parameters
            self.client = client
            self.db = self.client[db_name]
            self.connection_params = connection_params.copy()
            self.connection_params["database"] = db_name
            self.connected = True
            self.current_database = db_name
            self.current_collection = None
            self.collection = None
            
            print(f"✓ Connected to MongoDB successfully (database: {db_name})")
            return True
            
        except Exception as e:
            self.connected = False
            raise ConnectionError(f"MongoDB connection failed: {str(e)}")

    def disconnect(self) -> None:
        """Disconnect from MongoDB"""
        if self.client is not None:
            self.client.close()
            self.client = None
            self.db = None
            self.collection = None
            self.connection_params = None
            self.connected = False
            self.current_database = None
            self.current_collection = None
            print("Disconnected from MongoDB")

    def is_connected(self) -> bool:
        """Check if MongoDB is connected"""
        if self.client is None or not self.connected:
            return False
        try:
            self.client.admin.command('ping')
            return True
        except Exception:
            self.connected = False
            return False

    def get_connection_params(self) -> Optional[Dict[str, Any]]:
        """Get current connection parameters"""
        return self.connection_params

    def get_databases(self) -> List[str]:
        """List all databases in the connected MongoDB server"""
        if not self.connected:
            raise RuntimeError("MongoDB not connected")
        
        try:
            db_list = self.client.list_database_names()
            return db_list
        except Exception as e:
            raise RuntimeError(f"Failed to list databases: {str(e)}")

    def select_database(self, db_name: str) -> bool:
        """Switch to a specific database"""
        if not self.connected:
            raise RuntimeError("MongoDB not connected")
        
        try:
            # Check if database exists (optional - MongoDB creates on first write)
            # For now, we'll just switch to it
            self.db = self.client[db_name]
            self.current_database = db_name
            self.current_collection = None
            self.collection = None
            
            # Update connection params
            if self.connection_params:
                self.connection_params["database"] = db_name
            
            print(f"Switched to database: {db_name}")
            return True
        except Exception as e:
            raise RuntimeError(f"Failed to switch to database '{db_name}': {str(e)}")

    def get_collections(self) -> List[str]:
        """List all collections in the current database"""
        if not self.connected or self.db is None:
            raise RuntimeError("MongoDB not connected or no database selected")
        
        try:
            collection_list = self.db.list_collection_names()
            return collection_list
        except Exception as e:
            raise RuntimeError(f"Failed to list collections: {str(e)}")

    def select_collection(self, collection_name: str) -> bool:
        """Switch to a specific collection"""
        if not self.connected or self.db is None:
            raise RuntimeError("MongoDB not connected or no database selected")
        
        try:
            self.collection = self.db[collection_name]
            self.current_collection = collection_name
            print(f"Switched to collection: {collection_name}")
            return True
        except Exception as e:
            raise RuntimeError(f"Failed to switch to collection '{collection_name}': {str(e)}")

    def get_server_info(self) -> Dict[str, Any]:
        """Get MongoDB server information"""
        if not self.connected:
            raise RuntimeError("MongoDB not connected")
        
        try:
            server_info = self.client.server_info()
            return {
                "version": server_info.get("version"),
                "git_version": server_info.get("gitVersion"),
                "modules": server_info.get("modules", [])
            }
        except Exception as e:
            raise RuntimeError(f"Failed to get server info: {str(e)}")

    # ========================================================================
    # Query execution methods for NL2Query on MongoDB
    # ========================================================================

    def get_collection_schema(self) -> Dict[str, Any]:
        """Infer collection schema by sampling documents"""
        if not self.connected or self.db is None:
            raise RuntimeError("MongoDB not connected or no database selected")
        
        if self.collection is None or not self.current_collection:
            raise RuntimeError("No collection selected. Use /mongodb/select-collection first.")
        
        try:
            # Sample up to 10 documents to infer schema
            sample_docs = list(self.collection.find().limit(10))
            
            if not sample_docs:
                return {"fields": {}, "sample_count": 0, "message": "Collection is empty"}
            
            # Collect all unique field names and their types
            field_info = {}
            for doc in sample_docs:
                for key, value in doc.items():
                    if key == "_id":
                        continue
                    type_name = type(value).__name__
                    if key not in field_info:
                        field_info[key] = {
                            "types": set(),
                            "sample_values": []
                        }
                    field_info[key]["types"].add(type_name)
                    if len(field_info[key]["sample_values"]) < 3:
                        # Store sample values (truncate strings)
                        if isinstance(value, str) and len(value) > 100:
                            field_info[key]["sample_values"].append(value[:100] + "...")
                        elif isinstance(value, (dict, list)):
                            field_info[key]["sample_values"].append(str(value)[:100])
                        else:
                            field_info[key]["sample_values"].append(value)
            
            # Convert sets to lists for JSON serialization
            schema = {}
            for key, info in field_info.items():
                schema[key] = {
                    "types": list(info["types"]),
                    "sample_values": [str(v) for v in info["sample_values"]]
                }
            
            return {
                "collection": self.current_collection,
                "database": self.current_database,
                "fields": schema,
                "sample_count": len(sample_docs),
                "total_documents": self.collection.estimated_document_count()
            }
        except Exception as e:
            raise RuntimeError(f"Failed to get collection schema: {str(e)}")

    def get_schema_description(self) -> str:
        """Get a human-readable schema description for the LLM"""
        schema = self.get_collection_schema()
        
        lines = [f"Collection: {schema.get('collection', 'unknown')}"]
        lines.append(f"Database: {schema.get('database', 'unknown')}")
        lines.append(f"Total documents: {schema.get('total_documents', 'unknown')}")
        lines.append(f"Fields:")
        
        for field_name, field_info in schema.get("fields", {}).items():
            types = ", ".join(field_info.get("types", []))
            samples = ", ".join(field_info.get("sample_values", [])[:2])
            lines.append(f"  - {field_name} ({types}): e.g. {samples}")
        
        return "\n".join(lines)

    def execute_query(self, query_dict: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Execute a MongoDB query from a parsed query dict"""
        if not self.connected or self.collection is None:
            raise RuntimeError("MongoDB not connected or no collection selected")
        
        try:
            filter_query = query_dict.get("filter", {})
            projection = query_dict.get("projection", None)
            sort = query_dict.get("sort", None)
            limit = query_dict.get("limit", 100)  # Default limit to prevent huge results
            
            # Build cursor
            if projection:
                cursor = self.collection.find(filter_query, projection)
            else:
                cursor = self.collection.find(filter_query)
            
            # Apply sort
            if sort and isinstance(sort, dict):
                sort_list = [(k, v) for k, v in sort.items()]
                cursor = cursor.sort(sort_list)
            
            # Apply limit
            if limit:
                cursor = cursor.limit(int(limit))
            
            # Convert to list and stringify ObjectId
            results = []
            for doc in cursor:
                if "_id" in doc:
                    doc["_id"] = str(doc["_id"])
                # Convert any datetime objects to strings
                for key, value in doc.items():
                    if isinstance(value, datetime):
                        doc[key] = value.isoformat()
                results.append(doc)
            
            return results
        except Exception as e:
            raise RuntimeError(f"MongoDB query execution failed: {str(e)}")

    # ========================================================================
    # Legacy methods for backward compatibility with existing functionality
    # ========================================================================

    def save_result(self, result: Dict[str, Any]) -> str:
        """Save query result to MongoDB (legacy method)"""
        if not self.is_connected():
            # Try to reconnect using legacy method
            self._legacy_connect()
            if not self.is_connected():
                print("Warning: MongoDB not connected, result not saved.")
                return None
        
        try:
            # Ensure we have a collection to save to
            if self.collection is None:
                # Default to query_results collection
                if self.db is None:
                    self.db = self.client[self.current_database or "admin"]
                self.collection = self.db["query_results"]
                self.current_collection = "query_results"
            
            # Create a deep copy to avoid modifying the original result
            result_copy = deepcopy(result)
            
            # Ensure timestamp is datetime object for MongoDB
            if "timestamp" in result_copy and isinstance(result_copy["timestamp"], str):
                try:
                    result_copy["timestamp"] = datetime.fromisoformat(result_copy["timestamp"])
                except ValueError:
                    pass
            elif "timestamp" not in result_copy:
                result_copy["timestamp"] = datetime.now()

            # Insert document
            inserted_id = self.collection.insert_one(result_copy).inserted_id
            return str(inserted_id)
        except Exception as e:
            print(f"Error saving to MongoDB: {e}")
            return None

    def get_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get history of queries from MongoDB (legacy method)"""
        if not self.is_connected():
            return []
        
        try:
            # Ensure we have a collection
            if self.collection is None:
                if self.db is None:
                    self.db = self.client[self.current_database or "admin"]
                self.collection = self.db["query_results"]
            
            cursor = self.collection.find().sort("timestamp", -1).limit(limit)
            results = []
            for doc in cursor:
                doc["_id"] = str(doc["_id"])
                results.append(doc)
            return results
        except Exception as e:
            print(f"Error fetching history from MongoDB: {e}")
            return []

    def enable_sharing(self, doc_id: str, expiry_hours: int = 24) -> Dict[str, Any]:
        """Enable sharing for a MongoDB document (legacy method)"""
        if not self.is_connected():
            raise RuntimeError("MongoDB not connected")
        
        try:
            from bson.objectid import ObjectId
            from datetime import timedelta
            
            # Ensure we have a collection
            if self.collection is None:
                if self.db is None:
                    self.db = self.client[self.current_database or "admin"]
                self.collection = self.db["query_results"]
            
            expires_at = datetime.now() + timedelta(hours=expiry_hours)
            
            # Update document to enable sharing
            result = self.collection.update_one(
                {"_id": ObjectId(doc_id)},
                {"$set": {
                    "share_enabled": True,
                    "share_expires_at": expires_at,
                    "share_created_at": datetime.now()
                }}
            )
            
            if result.matched_count == 0:
                raise ValueError(f"Document {doc_id} not found")
            
            # Return the updated document info
            doc = self.collection.find_one({"_id": ObjectId(doc_id)})
            doc["_id"] = str(doc["_id"])
            return doc
            
        except Exception as e:
            print(f"Error enabling sharing: {e}")
            raise

    def get_shared_result(self, doc_id: str) -> Dict[str, Any]:
        """Get a shared result by MongoDB ID (legacy method)"""
        if not self.is_connected():
            return None
        
        try:
            from bson.objectid import ObjectId
            
            # Ensure we have a collection
            if self.collection is None:
                if self.db is None:
                    self.db = self.client[self.current_database or "admin"]
                self.collection = self.db["query_results"]
            
            # Find document and check permissions/expiry
            doc = self.collection.find_one({"_id": ObjectId(doc_id)})
            
            if not doc or not doc.get("share_enabled", False):
                return None
            
            # Check if expired
            expires_at = doc.get("share_expires_at")
            if expires_at and datetime.now() > expires_at:
                # Cleanup expired share
                self.collection.update_one(
                    {"_id": ObjectId(doc_id)},
                    {"$set": {"share_enabled": False}}
                )
                return None
            
            # Log access
            self.collection.update_one(
                {"_id": ObjectId(doc_id)},
                {
                    "$inc": {"access_count": 1},
                    "$set": {"last_accessed": datetime.now()}
                }
            )
            
            doc["_id"] = str(doc["_id"])
            return doc
            
        except Exception as e:
            print(f"Error getting shared result: {e}")
            return None
    def push_postgres_schema(self, schema_data: Dict[str, Any]) -> str:
        """Push a PostgreSQL schema definition into MongoDB with Smart Update (Upsert)"""
        try:
            if self.client is None:
                self._legacy_connect()
                
            if self.client is None:
                print("Cannot push schema: MongoDB not connected.")
                return None
                
            source_db = self.client["metadata_store"]
            schema_collection = source_db["postgres_schemas"]
            
            host = schema_data.get("host")
            db_name = schema_data.get("database")
            current_schemas = schema_data.get("schemas", {})
            
            # Find if this database already has an entry
            existing = schema_collection.find_one({"host": host, "database": db_name})
            
            now = datetime.now()
            
            if existing:
                # Compare the actual schema structure
                if existing.get("schemas") == current_schemas:
                    # SCHEMA UNCHANGED: Just update last_seen
                    schema_collection.update_one(
                        {"_id": existing["_id"]},
                        {"$set": {"last_seen": now}}
                    )
                    print(f"✓ Schema for '{db_name}' unchanged. Updated last_seen timestamp in MongoDB.")
                    return str(existing["_id"])
                else:
                    # SCHEMA CHANGED: Replace with new content and increment version
                    schema_data["updated_at"] = now
                    schema_data["last_seen"] = now
                    schema_data["version"] = existing.get("version", 1) + 1
                    
                    # Ensure we don't carry the old timestamp in comparison again later
                    # (Though we compare 'schemas' key specifically above)
                    
                    schema_collection.replace_one({"_id": existing["_id"]}, schema_data)
                    print(f"⚠ Schema change detected for '{db_name}'! Updated record to version {schema_data['version']} in MongoDB.")
                    return str(existing["_id"])
            else:
                # NEW DATABASE: Create first entry
                schema_data["created_at"] = now
                schema_data["last_seen"] = now
                schema_data["version"] = 1
                
                result = schema_collection.insert_one(schema_data)
                print(f"✓ New entry: Pushed initial PostgreSQL schema for '{db_name}' to MongoDB.")
                
            # ALSO: Upsert individual table metadata for easier querying
            table_metadata_coll = source_db["table_metadata"]
            for schema_name, tables in current_schemas.items():
                for table_name, columns in tables.items():
                    table_metadata_coll.update_one(
                        {"host": host, "database": db_name, "schema": schema_name, "table": table_name},
                        {"$set": {
                            "columns": columns,
                            "last_updated": now,
                            "column_names": [c["name"] for c in columns]
                        }},
                        upsert=True
                    )
            print(f"✓ Synced metadata for {sum(len(t) for t in current_schemas.values())} tables to 'table_metadata' collection.")
            
            return str(existing["_id"]) if existing else str(result.inserted_id)
                
        except Exception as e:
            print(f"Failed to push postgres schema to MongoDB: {e}")
            return None
    def get_postgres_schema(self, host: str, database: str) -> Optional[Dict[str, Any]]:
        """Retrieve the latest PostgreSQL schema from MongoDB metadata store"""
        try:
            if self.client is None:
                self._legacy_connect()
            
            if self.client is None:
                return None
                
            source_db = self.client["metadata_store"]
            schema_collection = source_db["postgres_schemas"]
            
            return schema_collection.find_one({"host": host, "database": database})
        except Exception as e:
            print(f"Error retrieving postgres schema from MongoDB: {e}")
            return None

    def search_relevant_tables(self, host: str, database: str, table_names: List[str]) -> List[Dict[str, Any]]:
        """Fetch full metadata for specific tables from MongoDB"""
        try:
            if self.client is None:
                self._legacy_connect()
                
            if self.client is None:
                return []
                
            source_db = self.client["metadata_store"]
            table_metadata_coll = source_db["table_metadata"]
            
            cursor = table_metadata_coll.find({
                "host": host,
                "database": database,
                "table": {"$in": table_names}
            })
            
            return list(cursor)
        except Exception as e:
            print(f"Error searching table metadata in MongoDB: {e}")
            return []
    def query_table_metadata(self, host: str, database: str, filter_json: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Search table metadata using a raw filter JSON"""
        try:
            if self.client is None:
                self._legacy_connect()
            
            if self.client is None:
                return []
                
            source_db = self.client["metadata_store"]
            table_metadata_coll = source_db["table_metadata"]
            
            # Base filter scoped to current DB
            base_filter = {"host": host, "database": database}
            
            # Merge with LLM-generated filter
            final_filter = {"$and": [base_filter, filter_json]}
            
            cursor = table_metadata_coll.find(final_filter)
            return list(cursor)
        except Exception as e:
            print(f"Error querying table metadata in MongoDB: {e}")
            return []
