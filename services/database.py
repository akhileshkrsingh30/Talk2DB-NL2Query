import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Optional, Dict, Any, List, Union
import urllib.parse
from langchain_community.utilities.sql_database import SQLDatabase
import json
from datetime import datetime, date, time
from decimal import Decimal

from config import settings
from utils.database import make_db_cache_key

def convert_to_serializable(obj: Any) -> Any:
    """Convert database objects to JSON-serializable formats"""
    if isinstance(obj, (datetime, date, time)):
        return obj.isoformat()
    elif isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, (bytes, bytearray)):
        try:
            return obj.decode('utf-8')
        except UnicodeDecodeError:
            return str(obj)
    elif hasattr(obj, '__iter__') and not isinstance(obj, (str, bytes)):
        try:
            return [convert_to_serializable(item) for item in obj]
        except:
            return str(obj)
    else:
        return obj

def convert_realdict_to_dict(rows: List[Any]) -> List[Dict[str, Any]]:
    """Convert RealDictRow objects to regular dictionaries with serializable values"""
    if not rows:
        return []
    
    result = []
    for row in rows:
        if hasattr(row, '_asdict'):  # RealDictRow has _asdict method
            row_dict = dict(row)
        elif hasattr(row, 'items'):  # Already a dict-like object
            row_dict = dict(row)
        else:
            # Convert other types to string representation
            row_dict = {"value": str(row)}
        
        # Convert all values to serializable formats
        serializable_row = {}
        for key, value in row_dict.items():
            serializable_row[key] = convert_to_serializable(value)
        
        result.append(serializable_row)
    
    return result

class DatabaseService:
    def __init__(self):
        self.connection_params: Optional[Dict[str, Any]] = None
        self.connected = False
        self.db_version = None
        self._schema_cache: Dict[str, Dict[str, Any]] = {}
        self._schema_cache_ttl_seconds = 300
        
    def connect(self, connection_params: Dict[str, Any]) -> bool:
        """Establish database connection"""
        try:
            # Validate required parameters
            required_fields = ["host", "port", "user", "password"]
            if not all(connection_params.get(field) for field in required_fields):
                raise ValueError(f"Required connection fields missing: {', '.join([f for f in required_fields if not connection_params.get(f)])}")
                
            if not str(connection_params["port"]).isdigit():
                raise ValueError("Port must be a number")
                
            # Default to 'postgres' if no database name provided
            db_name = connection_params.get("database") or "postgres"
                
            # Test connection
            with psycopg2.connect(
                host=connection_params["host"],
                port=int(connection_params["port"]),
                database=db_name,
                user=connection_params["user"],
                password=connection_params["password"],
                connect_timeout=5,
            ) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT version()")
                    self.db_version = cur.fetchone()[0]
            
            # Store connection parameters if successful
            final_params = connection_params.copy()
            final_params["database"] = db_name
            self.connection_params = final_params
            self.connected = True
            return True
            
        except psycopg2.OperationalError as e:
            raise ConnectionError(f"Database connection failed: {str(e)}")
        except Exception as e:
            raise RuntimeError(f"Connection error: {str(e)}")
    
    def disconnect(self):
        """Disconnect from database"""
        self.connection_params = None
        self.connected = False
        self.db_version = None
        self._schema_cache = {}
    
    def is_connected(self) -> bool:
        """Check if database is connected"""
        return self.connected
    
    def get_connection_params(self) -> Optional[Dict[str, Any]]:
        """Get current connection parameters"""
        return self.connection_params
    
    def get_db_version(self) -> Optional[str]:
        """Get database version"""
        return self.db_version
    
    def get_databases(self) -> List[str]:
        """List all databases in the connected server"""
        if not self.connected:
            raise RuntimeError("Database not connected")
            
        try:
            with self.create_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT datname FROM pg_database WHERE datistemplate = false;")
                    rows = cursor.fetchall()
                    return [row['datname'] if isinstance(row, dict) else row[0] for row in rows]
        except Exception as e:
            raise RuntimeError(f"Failed to list databases: {str(e)}")
    
    def select_database(self, db_name: str) -> bool:
        """Switch to a specific database using current connection credentials"""
        if not self.connection_params:
            raise RuntimeError("Must connect to server first with /connect")
            
        # Create a copy of existing params with the new database name
        new_params = self.connection_params.copy()
        new_params["database"] = db_name
        
        # Attempt to connect to the new database
        try:
            with psycopg2.connect(
                host=new_params["host"],
                port=int(new_params["port"]),
                database=new_params["database"],
                user=new_params["user"],
                password=new_params["password"],
                connect_timeout=5,
            ) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT version()")
                    self.db_version = cur.fetchone()[0]
            
            # Update connection params and state
            self.connection_params = new_params
            self.connected = True
            self._schema_cache = {} # Clear schema cache for the new database
            return True
        except Exception as e:
            raise RuntimeError(f"Failed to switch to database '{db_name}': {str(e)}")

    def create_connection(self) -> psycopg2.extensions.connection:
        """Create a new database connection"""
        if not self.connected:
            raise RuntimeError("Database not connected")
            
        return psycopg2.connect(
            host=self.connection_params["host"],
            port=int(self.connection_params["port"]),
            database=self.connection_params["database"],
            user=self.connection_params["user"],
            password=self.connection_params["password"],
            cursor_factory=RealDictCursor
        )
    
    def get_langchain_db(self) -> SQLDatabase:
        """Get LangChain SQLDatabase instance"""
        if not self.connected:
            raise RuntimeError("Database not connected")
            
        username = urllib.parse.quote_plus(self.connection_params["user"])
        password = urllib.parse.quote_plus(self.connection_params["password"])
        host = self.connection_params["host"]
        port = self.connection_params["port"]
        dbname = self.connection_params["database"]
        
        db_uri = f"postgresql://{username}:{password}@{host}:{port}/{dbname}"
        return SQLDatabase.from_uri(db_uri)
    
    def execute_query(self, sql_query: str) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
        """Execute SQL query and return results"""
        if not self.connected:
            raise RuntimeError("Database not connected")
            
        try:
            with self.create_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(sql_query)
                    
                    if sql_query.strip().lower().startswith("select"):
                        results = cursor.fetchall()
                        # Convert RealDictRow objects to regular dictionaries
                        return convert_realdict_to_dict(results)
                    else:
                        conn.commit()
                        return {
                            "status": "Command executed successfully", 
                            "rows_affected": cursor.rowcount,
                            "query": sql_query.strip()
                        }
                        
        except psycopg2.Error as e:
            raise RuntimeError(f"Query execution failed: {str(e)}")

    def get_simplified_schema(self) -> str:
        if not self.connected:
            raise RuntimeError("Database not connected")
        key = make_db_cache_key(self.connection_params or {})
        try:
            entry = self._schema_cache.get(key)
            if entry:
                generated_at = entry.get("generated_at")
                if isinstance(generated_at, datetime):
                    age = (datetime.now() - generated_at).total_seconds()
                    if age < getattr(self, "_schema_cache_ttl_seconds", 300):
                        return entry["text"]
        except Exception:
            pass
        try:
            with self.create_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT table_schema, table_name, column_name, data_type, is_nullable, ordinal_position
                        FROM information_schema.columns
                        WHERE table_schema NOT IN ('pg_catalog','information_schema')
                        ORDER BY table_schema, table_name, ordinal_position
                        """
                    )
                    cols = cursor.fetchall()
                    cursor.execute(
                        """
                        SELECT kcu.table_schema, kcu.table_name, kcu.column_name
                        FROM information_schema.table_constraints tc
                        JOIN information_schema.key_column_usage kcu
                          ON tc.constraint_name = kcu.constraint_name
                         AND tc.table_schema = kcu.table_schema
                         AND tc.table_name = kcu.table_name
                        WHERE tc.constraint_type = 'PRIMARY KEY'
                          AND tc.table_schema NOT IN ('pg_catalog','information_schema')
                        """
                    )
                    pk_rows = cursor.fetchall()
        except psycopg2.Error as e:
            raise RuntimeError(f"Schema fetch failed: {str(e)}")
        pk_set = set()
        for r in pk_rows:
            try:
                pk_set.add((r["table_schema"], r["table_name"], r["column_name"]))
            except Exception:
                pass
        tables: Dict[tuple, List[Dict[str, Any]]] = {}
        for r in cols:
            try:
                k = (r["table_schema"], r["table_name"])
                tables.setdefault(k, []).append(r)
            except Exception:
                continue
        MAX_TABLES = 50
        MAX_COLS = 60
        lines: List[str] = []
        count_tables = 0
        for (schema, table), columns in tables.items():
            if count_tables >= MAX_TABLES:
                break
            parts: List[str] = []
            for col in columns[:MAX_COLS]:
                name = col.get("column_name")
                dtype = col.get("data_type")
                nullable = col.get("is_nullable")
                is_pk = (schema, table, name) in pk_set
                suffix = " PK" if is_pk else ""
                if nullable == "NO":
                    suffix += " NOT NULL"
                parts.append(f"{name} {dtype}{suffix}")
            lines.append(f"{schema}.{table}: " + ", ".join(parts))
            count_tables += 1
        text = "\n".join(lines)
        if len(text) > 16000:
            text = text[:16000]
        try:
            self._schema_cache[key] = {"text": text, "generated_at": datetime.now()}
        except Exception:
            pass
        return text