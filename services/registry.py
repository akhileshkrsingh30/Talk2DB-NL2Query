from typing import Optional
from services.database import DatabaseService
from services.llm import LLMService
from services.sharing import SharingService

class ServiceRegistry:
    """Global service registry for dependency injection"""
    
    def __init__(self):
        self._db_service: Optional[DatabaseService] = None
        self._llm_service: Optional[LLMService] = None
        self._sharing_service: Optional[SharingService] = None
    
    def set_db_service(self, service: DatabaseService):
        self._db_service = service
    
    def get_db_service(self) -> DatabaseService:
        if self._db_service is None:
            raise RuntimeError("Database service not initialized")
        return self._db_service
    
    def set_llm_service(self, service: LLMService):
        self._llm_service = service
    
    def get_llm_service(self) -> LLMService:
        if self._llm_service is None:
            raise RuntimeError("LLM service not initialized")
        return self._llm_service
    
    def set_sharing_service(self, service: SharingService):
        self._sharing_service = service
    
    def get_sharing_service(self) -> SharingService:
        if self._sharing_service is None:
            raise RuntimeError("Sharing service not initialized")
        return self._sharing_service
    
    def cleanup(self):
        """Cleanup all services"""
        if self._db_service:
            self._db_service.disconnect()
        self._db_service = None
        self._llm_service = None
        self._sharing_service = None

# Global service registry instance
service_registry = ServiceRegistry()
