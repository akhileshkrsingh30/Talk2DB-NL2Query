from typing import Optional
from services.database import DatabaseService
from services.llm import LLMService
from services.sharing import SharingService
from services.billing.billing_service import BillingService
from services.mongodb import MongoDBService
from services.neo4j_service import Neo4jService


class ServiceRegistry:
    """Global service registry for dependency injection"""
    
    def __init__(self):
        self._db_service: Optional[DatabaseService] = None
        self._llm_service: Optional[LLMService] = None
        self._sharing_service: Optional[SharingService] = None
        self._billing_service: Optional[BillingService] = None
        self._mongodb_service: Optional[MongoDBService] = None
        self._neo4j_service: Optional[Neo4jService] = None
    
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
    
    def set_billing_service(self, service: BillingService):
        self._billing_service = service
    
    def get_billing_service(self) -> BillingService:
        if self._billing_service is None:
            raise RuntimeError("Billing service not initialized")
        return self._billing_service

    def set_mongodb_service(self, service: MongoDBService):
        self._mongodb_service = service
    
    def get_mongodb_service(self) -> MongoDBService:
        if self._mongodb_service is None:
            raise RuntimeError("MongoDB service not initialized")
        return self._mongodb_service

    def set_neo4j_service(self, service: Neo4jService):
        self._neo4j_service = service
    
    def get_neo4j_service(self) -> Neo4jService:
        if self._neo4j_service is None:
            raise RuntimeError("Neo4j service not initialized")
        return self._neo4j_service
    
    def cleanup(self):
        """Cleanup all services"""
        if self._db_service:
            self._db_service.disconnect()
        self._db_service = None
        self._llm_service = None
        self._sharing_service = None
        self._billing_service = None
        self._mongodb_service = None
        if self._neo4j_service:
            self._neo4j_service.disconnect()
        self._neo4j_service = None

# Global service registry instance
service_registry = ServiceRegistry()
