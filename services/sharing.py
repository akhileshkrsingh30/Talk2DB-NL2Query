import uuid
import json
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from pathlib import Path

class SharingService:
    def __init__(self, storage_dir: str = "shared_results"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(exist_ok=True)
        self.shared_results: Dict[str, Dict[str, Any]] = {}
        
    def share_result(self, result: Dict[str, Any], expiry_hours: int = 24) -> str:
        """Share a query result and return share ID"""
        share_id = str(uuid.uuid4())
        expires_at = datetime.now() + timedelta(hours=expiry_hours)
        
        shared_data = {
            "id": share_id,
            "result": result,
            "created_at": datetime.now(),
            "expires_at": expires_at,
            "access_count": 0,
            "last_accessed": None
        }
        
        # Store in memory (in production, use a database)
        self.shared_results[share_id] = shared_data
        
        # Also save to file for persistence
        try:
            file_path = self.storage_dir / f"{share_id}.json"
            with open(file_path, 'w') as f:
                json.dump(shared_data, f, default=str, indent=2)
        except Exception as e:
            print(f"Warning: Could not persist shared result to file: {e}")
        
        return share_id
    
    def get_shared_result(self, share_id: str) -> Optional[Dict[str, Any]]:
        """Get a shared result by ID"""
        # Check memory first
        if share_id in self.shared_results:
            shared_data = self.shared_results[share_id]
        else:
            # Try loading from file
            try:
                file_path = self.storage_dir / f"{share_id}.json"
                if file_path.exists():
                    with open(file_path, 'r') as f:
                        shared_data = json.load(f)
                        # Convert string dates back to datetime
                        shared_data["created_at"] = datetime.fromisoformat(shared_data["created_at"])
                        shared_data["expires_at"] = datetime.fromisoformat(shared_data["expires_at"])
                        if shared_data["last_accessed"]:
                            shared_data["last_accessed"] = datetime.fromisoformat(shared_data["last_accessed"])
                        self.shared_results[share_id] = shared_data
                else:
                    return None
            except Exception:
                return None
        
        # Check if expired
        if datetime.now() > shared_data["expires_at"]:
            self._delete_shared_result(share_id)
            return None
        
        # Update access info
        shared_data["access_count"] += 1
        shared_data["last_accessed"] = datetime.now()
        
        return shared_data
    
    def _delete_shared_result(self, share_id: str):
        """Delete an expired shared result"""
        if share_id in self.shared_results:
            del self.shared_results[share_id]
        
        try:
            file_path = self.storage_dir / f"{share_id}.json"
            if file_path.exists():
                file_path.unlink()
        except Exception:
            pass
    
    def cleanup_expired(self):
        """Clean up expired shared results"""
        current_time = datetime.now()
        expired_ids = []
        
        for share_id, data in self.shared_results.items():
            if current_time > data["expires_at"]:
                expired_ids.append(share_id)
        
        for share_id in expired_ids:
            self._delete_shared_result(share_id)
    
    def list_shared_results(self, limit: int = 50) -> list:
        """List all active shared results (metadata only)"""
        self.cleanup_expired()
        results = []
        
        for share_id, data in list(self.shared_results.items())[:limit]:
            results.append({
                "id": share_id,
                "created_at": data["created_at"],
                "expires_at": data["expires_at"],
                "access_count": data["access_count"],
                "last_accessed": data["last_accessed"],
                "query": data["result"].get("query", "Unknown"),
                "sql_queries_count": len(data["result"].get("sql_queries", []))
            })
        
        return results
