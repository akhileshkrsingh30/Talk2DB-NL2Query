import json
import os
import sys
import requests

# Insert parent directory to path
sys.path.insert(0, os.path.dirname(__file__))
from config import settings

def dump_all_memories():
    provider = settings.mem0_vector_store_provider.lower()
    print(f"--- DUMPING MEM0 ({provider.upper()}) MEMORY DATABASE ---")
    
    if provider == "qdrant":
        url = settings.mem0_qdrant_url
        if not url:
            url = f"http://{settings.mem0_qdrant_host}:{settings.mem0_qdrant_port}"
        
        print(f"Connecting to Qdrant: {url}")
        print(f"Collection: {settings.mem0_collection_name}\n")
        
        headers = {}
        if settings.mem0_qdrant_api_key:
            headers["api-key"] = settings.mem0_qdrant_api_key
            
        scroll_url = f"{url}/collections/{settings.mem0_collection_name}/points/scroll"
        
        try:
            response = requests.post(
                scroll_url,
                json={"limit": 1000, "with_payload": True, "with_vector": False},
                headers=headers,
                timeout=10
            )
            
            if response.status_code != 200:
                print(f"Error: Qdrant API returned {response.status_code} - {response.text}")
                return
                
            points = response.json().get("result", {}).get("points", [])
            print(f"Found {len(points)} memories:\n")
            print("-" * 100)
            for i, pt in enumerate(points, 1):
                payload = pt.get("payload", {})
                meta = payload.get("metadata") or {}
                if isinstance(meta, str):
                    try:
                        meta = json.loads(meta)
                    except Exception:
                        pass
                memory_text = payload.get("memory") or payload.get("text") or "N/A"
                
                print(f"[{i}] ID: {pt.get('id')}")
                print(f"    Owner: user_id={payload.get('user_id')} | agent_id={payload.get('agent_id')}")
                print(f"    Memory Text: \"{memory_text}\"")
                print(f"    Metadata: {json.dumps(meta, indent=2)}")
                print("-" * 100)
                
        except Exception as e:
            print(f"Error connecting to Qdrant: {e}")
            
    else:
        # pgvector (PostgreSQL)
        import psycopg2
        from psycopg2.extras import RealDictCursor
        connection_string = settings.mem0_pg_connection_string
        table_name = settings.mem0_collection_name
        
        print(f"Connecting to PostgreSQL: {connection_string}")
        print(f"Table name: {table_name}\n")
        
        try:
            conn = psycopg2.connect(connection_string)
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            # Verify table exists
            cursor.execute(
                "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = %s)",
                (table_name,)
            )
            exists = cursor.fetchone()["exists"]
            
            if not exists:
                print(f"Error: The table '{table_name}' does not exist in the database.")
                cursor.close()
                conn.close()
                return
                
            # Get column names dynamically (excluding embedding/vectors)
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
                if "vector" in data_type.lower() or "embedding" in col_name.lower():
                    continue
                valid_cols.append(col_name)
                
            if not valid_cols:
                valid_cols = ["id", "metadata", "user_id"]
                
            cols_str = ", ".join(valid_cols)
            
            # Fetch rows
            cursor.execute(f"SELECT {cols_str} FROM {table_name} ORDER BY id ASC")
            rows = cursor.fetchall()
            
            print(f"Found {len(rows)} memories:\n")
            print("-" * 100)
            for i, row in enumerate(rows, 1):
                memory_text = row.get("memory") or row.get("text") or "N/A"
                user_id = row.get("user_id") or "N/A"
                agent_id = row.get("agent_id") or "N/A"
                meta = row.get("metadata") or {}
                if isinstance(meta, str):
                    try:
                        meta = json.loads(meta)
                    except Exception:
                        pass
                
                print(f"[{i}] ID: {row.get('id')}")
                print(f"    Owner: user_id={user_id} | agent_id={agent_id}")
                print(f"    Memory Text: \"{memory_text}\"")
                print(f"    Metadata: {json.dumps(meta, indent=2)}")
                print("-" * 100)
                
            cursor.close()
            conn.close()
            
        except Exception as e:
            print(f"Error occurred: {e}")

if __name__ == "__main__":
    dump_all_memories()
