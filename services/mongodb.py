from pymongo import MongoClient
from datetime import datetime
from typing import Dict, Any, List
from copy import deepcopy
from config import settings

class MongoDBService:
    def __init__(self):
        self.client = None
        self.db = None
        self.collection = None
        self._connect()

    def _connect(self):
        try:
            self.client = MongoClient(settings.mongo_uri)
            self.db = self.client[settings.mongo_db_name]
            # Use 'query_results' collection as specified in requirements
            self.collection = self.db["query_results"]
            print(f"Connected to MongoDB: {settings.mongo_uri}")
        except Exception as e:
            print(f"Failed to connect to MongoDB: {e}")
            self.client = None

    def is_connected(self) -> bool:
        if not self.client:
            return False
        try:
            # The is_connected check should actually verify the connection
            self.client.admin.command('ping')
            return True
        except Exception:
            return False

    def save_result(self, result: Dict[str, Any]) -> str:
        """Save query result to MongoDB"""
        if not self.is_connected():
            self._connect()
            if not self.is_connected():
                print("Warning: MongoDB not connected, result not saved.")
                return None
        
        try:
            # Create a deep copy to avoid modifying the original result (prevents _id leakage)
            result_copy = deepcopy(result)
            
            # Ensure timestamp is datetime object for MongoDB
            if "timestamp" in result_copy and isinstance(result_copy["timestamp"], str):
                 try:
                     result_copy["timestamp"] = datetime.fromisoformat(result_copy["timestamp"])
                 except ValueError:
                     # Carry on if parsing fails
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
        """Get history of queries from MongoDB"""
        if not self.is_connected():
            return []
        
        try:
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
        """Enable sharing for a MongoDB document"""
        if not self.is_connected():
            raise RuntimeError("MongoDB not connected")
        
        try:
            from bson.objectid import ObjectId
            from datetime import timedelta
            
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
        """Get a shared result by MongoDB ID"""
        if not self.is_connected():
            return None
        
        try:
            from bson.objectid import ObjectId
            
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
