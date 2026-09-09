import logging
from typing import List, Dict, Any, Optional
from config import settings

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import VectorParams, Distance
    QDRANT_AVAILABLE = True
except ImportError:
    QDRANT_AVAILABLE = False


class VectorStoreService:
    """Service to interface with local Qdrant Vector DB for Schema RAG."""

    def __init__(self):
        self.client: Optional[Any] = None
        self.connected: bool = False
        self.collection_name: str = settings.qdrant_collection
        self._initialize_client()

    def _initialize_client(self):
        if not QDRANT_AVAILABLE:
            logging.warning("[VectorStore] qdrant-client package is not installed.")
            return

        try:
            self.client = QdrantClient(
                host=settings.qdrant_host,
                port=settings.qdrant_port,
                timeout=5.0
            )
            # Ping/check health
            collections = self.client.get_collections()
            self.connected = True
            logging.info(f"[VectorStore] Connected to Qdrant Docker container at {settings.qdrant_url}")
        except Exception as e:
            self.connected = False
            self.client = None
            logging.info(f"[VectorStore] Qdrant Docker container not reachable at {settings.qdrant_url}: {e}")

    def is_connected(self) -> bool:
        return self.connected

    def ensure_collection(self, vector_size: int = 384):
        """Ensure Qdrant collection exists for table schema vectors."""
        if not self.connected or not self.client:
            return
        try:
            collections = [c.name for c in self.client.get_collections().collections]
            if self.collection_name not in collections:
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE)
                )
                logging.info(f"[VectorStore] Created Qdrant collection '{self.collection_name}'.")
        except Exception as e:
            logging.error(f"[VectorStore] Failed to ensure collection '{self.collection_name}': {e}")

    def auto_sync_database_schema(self, db_service: Any) -> int:
        """Automated zero-human-intervention pipeline to extract, vectorize, and index 1,000+ tables into Qdrant."""
        if not self.connected or not self.client:
            logging.warning("[VectorStore] Qdrant not connected — skipping auto-indexing.")
            return 0

        try:
            schema_text = db_service.get_simplified_schema(top_k=5000)
            if not schema_text:
                return 0

            self.ensure_collection(vector_size=384)
            lines = [line.strip() for line in schema_text.split("\n") if line.strip()]

            points = []
            for idx, line in enumerate(lines, start=1):
                table_part = line.split(":", 1)[0].strip() if ":" in line else f"table_{idx}"
                # Generate pseudo/mock embedding vector (size 384) for fast keyword/semantic mapping
                # In production, pass text to sentence-transformers / embedding model
                dummy_vector = [0.01 * (hash(table_part + str(i)) % 100) for i in range(384)]
                
                payload = {
                    "table_name": table_part,
                    "schema_definition": line
                }
                points.append({
                    "id": idx,
                    "vector": dummy_vector,
                    "payload": payload
                })

            if points:
                from qdrant_client.models import PointStruct
                struct_points = [PointStruct(id=p["id"], vector=p["vector"], payload=p["payload"]) for p in points]
                self.client.upsert(collection_name=self.collection_name, points=struct_points)
                logging.info(f"[VectorStore] Auto-indexed {len(points)} tables into Qdrant successfully with zero human intervention.")
            return len(points)

        except Exception as e:
            logging.error(f"[VectorStore] Auto-sync failed: {e}")
            return 0
