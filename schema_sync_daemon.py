import time
import hashlib
import json
import logging
import os
from dotenv import load_dotenv

from services.database import DatabaseService
from services.neo4j_service import Neo4jService
from config import settings

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

POLL_INTERVAL = 300  # Poll every 5 minutes to avoid overloading the source DB

def hash_schema(schema_dict):
    """Generate a consistent hash of the schema metadata to detect changes."""
    # Convert to JSON string (sort keys to ensure consistent hashing)
    schema_str = json.dumps(schema_dict, sort_keys=True)
    return hashlib.sha256(schema_str.encode('utf-8')).hexdigest()

def sync_daemon():
    logging.info("Starting Schema Knowledge Graph (SKG) Sync Daemon...")
    
    db = DatabaseService()
    neo = Neo4jService()
    
    # Configure Target
    db_name = os.getenv("DB_NAME")
    if not db_name:
        logging.error("DB_NAME not set in .env. Exiting.")
        return
        
    db_params = {
        'host': os.getenv("DB_HOST", "localhost"),
        'port': os.getenv("DB_PORT", "5432"),
        'database': db_name,
        'user': os.getenv("DB_USER", "postgres"),
        'password': os.getenv("DB_PASSWORD", ""),
        'db_type': os.getenv("DB_TYPE", "postgresql")
    }

    neo_uri = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
    neo_user = os.getenv("NEO4J_USER", "neo4j")
    neo_pass = os.getenv("NEO4J_PASSWORD", "Akhilesh842@")
    
    previous_hash = None
    
    while True:
        try:
            # 1. Connect and Fetch Latest State
            if not db.is_connected():
                db.connect(db_params)
                
            logging.info(f"Polling database '{db_name}' for DDL/Schema changes...")
            current_schema = db.get_schema_dict()
            current_hash = hash_schema(current_schema)
            
            # 2. Detect Delta/Changes
            if current_hash != previous_hash:
                logging.info(f"🚨 Schema change detected in '{db_name}'. Synchronizing to Neo4j...")
                
                if not neo.is_connected():
                    neo.connect(neo_uri, neo_user, neo_pass)

                # 3. Clean stale data & Replace (Idempotent update handling deletes)
                with neo.driver.session(database="neo4j") as s:
                    # Detach and delete all sub-nodes for this specific DB to handle removed tables/columns
                    s.run("""
                        MATCH (db:Database {name: $db_name})-[r:HAS_SCHEMA]->(sc) 
                        OPTIONAL MATCH (sc)-[*1..2]->(n) 
                        DETACH DELETE r, sc, n
                    """, db_name=db_name)
                    # Re-establish anchor
                    s.run("MERGE (db:Database {name: $db_name})", db_name=db_name)

                # 4. Push new state
                neo.push_schema(db_name, current_schema)
                logging.info(f"✅ SKG Synchronization complete for '{db_name}'.")
                
                previous_hash = current_hash
            else:
                logging.debug("No schema changes detected.")

        except Exception as e:
            logging.error(f"Sync error: {e}")
            # Reset connections on failure
            db.disconnect()
            neo.disconnect()
            
        finally:
            logging.info(f"Sleeping for {POLL_INTERVAL} seconds...")
            time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    sync_daemon()
