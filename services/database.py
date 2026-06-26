import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Optional, Dict, Any, List, Union
import urllib.parse
from langchain_community.utilities.sql_database import SQLDatabase
import json
from datetime import datetime, date, time
from decimal import Decimal

import logging
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

try:
    import pymysql as mysql
    mysql.connector = mysql
except ImportError:
    mysql = None

try:
    import pymssql
except ImportError:
    pymssql = None

try:
    import oracledb
except ImportError:
    oracledb = None


class DatabaseService:
    def __init__(self):
        self.connection_params: Optional[Dict[str, Any]] = None
        self.connected = False
        self.db_version = None
        self.db_type = "postgresql" # Default
        self._schema_cache: Dict[str, Dict[str, Any]] = {}
        self._schema_cache_ttl_seconds = 300
        
    def connect(self, connection_params: Dict[str, Any]) -> bool:
        """Establish database connection"""
        try:
            db_type = connection_params.get("db_type", settings.db_type).lower()
            if db_type in ["mssql", "sqlserver"]:
                self.db_type = "mssql"
            else:
                self.db_type = db_type
            
            # Validate required parameters (database is optional for Postgres but needed for MySQL sometimes)
            required_fields = ["host", "port", "user", "password"]
            missing_fields = []
            
            for field in required_fields:
                value = connection_params.get(field)
                if value is None or (isinstance(value, str) and not value.strip()):
                    missing_fields.append(field)
            
            if missing_fields:
                raise ValueError(f"Required connection fields missing or empty: {', '.join(missing_fields)}")
                
            db_name = connection_params.get("database") or ""
            
            if self.db_type in ["mysql", "mariadb"]:
                if mysql is None:
                    raise ImportError("mysql-connector-python is not installed. Required for MySQL/MariaDB support.")
                
                # Test connection for MySQL/MariaDB
                conn_config = {
                    "host": connection_params["host"],
                    "port": int(connection_params["port"]),
                    "user": connection_params["user"],
                    "password": connection_params["password"],
                    "database": db_name,
                    "connect_timeout": 5
                }
                # Remove empty database name if present for initial connection
                if not db_name:
                    del conn_config["database"]
                    
                with mysql.connect(**conn_config) as conn:
                    with conn.cursor() as cursor:
                        cursor.execute("SELECT VERSION()")
                    self.db_version = cursor.fetchone()[0]
                    cursor.close()
            elif self.db_type == "mssql":
                if pymssql is None:
                    raise ImportError("pymssql is not installed. Required for MSSQL support.")
                with pymssql.connect(
                    server=connection_params["host"],
                    port=connection_params["port"],
                    user=connection_params["user"],
                    password=connection_params["password"],
                    database=db_name or "master",
                    login_timeout=5
                ) as conn:
                    with conn.cursor() as cursor:
                        cursor.execute("SELECT @@VERSION")
                        row = cursor.fetchone()
                        self.db_version = row[0] if row else "Unknown MSSQL Version"
            elif self.db_type == "oracle":
                if oracledb is None:
                    raise ImportError("oracledb is not installed. Required for Oracle support.")
                dsn = f"{connection_params['host']}:{connection_params['port']}/{db_name}" if db_name else f"{connection_params['host']}:{connection_params['port']}"
                with oracledb.connect(
                    user=connection_params["user"],
                    password=connection_params["password"],
                    dsn=dsn
                ) as conn:
                    self.db_version = conn.version
            else:
                # Default to PostgreSQL
                if not db_name:
                    db_name = "postgres"
                    
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
            if db_name:
                final_params["database"] = db_name
            self.connection_params = final_params
            self.connected = True
            return True
            
        except Exception as e:
            self.connected = False
            if any(driver in str(e) for driver in ["psycopg2", "mysql", "pymssql", "oracledb"]):
                raise ConnectionError(f"Database connection failed: {str(e)}")
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
                cursor = conn.cursor()
                if self.db_type in ["mysql", "mariadb"]:
                    cursor.execute("SHOW DATABASES")
                elif self.db_type == "mssql":
                    cursor.execute("SELECT name FROM sys.databases WHERE state_desc = 'ONLINE'")
                elif self.db_type == "oracle":
                    cursor.execute("SELECT DISTINCT owner FROM all_tables")
                else:
                    cursor.execute("SELECT datname FROM pg_database WHERE datistemplate = false;")
                
                rows = cursor.fetchall()
                # Handle both tuple and dictionary results
                if self.db_type in ["mysql", "mariadb"]:
                    return [row[0] if isinstance(row, tuple) else row['Database'] for row in rows]
                elif self.db_type == "mssql":
                    return [row['name'] if isinstance(row, dict) else row[0] for row in rows]
                elif self.db_type == "oracle":
                    return [row[0] for row in rows]
                else:
                    return [row['datname'] if isinstance(row, dict) else row[0] for row in rows]
        except Exception as e:
            raise RuntimeError(f"Failed to list databases: {str(e)}")

    def get_tables(self) -> List[str]:
        """List all user tables in the connected database"""
        if not self.connected:
            raise RuntimeError("Database not connected")
            
        try:
            with self.create_connection() as conn:
                cursor = conn.cursor()
                if self.db_type in ["mysql", "mariadb"]:
                    cursor.execute(
                        """
                        SELECT table_name 
                        FROM information_schema.tables 
                        WHERE table_schema = %s AND table_type = 'BASE TABLE'
                        ORDER BY table_name
                        """, (self.connection_params["database"],)
                    )
                elif self.db_type == "mssql":
                    cursor.execute(
                        """
                        SELECT TABLE_NAME 
                        FROM INFORMATION_SCHEMA.TABLES 
                        WHERE TABLE_TYPE = 'BASE TABLE'
                        ORDER BY TABLE_NAME
                        """
                    )
                elif self.db_type == "oracle":
                    cursor.execute(
                        """
                        SELECT table_name 
                        FROM all_tables 
                        WHERE owner = %s
                        ORDER BY table_name
                        """, (self.connection_params["user"].upper(),)
                    )
                else:  # postgresql default
                    cursor.execute(
                        """
                        SELECT table_name 
                        FROM information_schema.tables 
                        WHERE table_schema NOT IN ('pg_catalog', 'information_schema') AND table_type = 'BASE TABLE'
                        ORDER BY table_name
                        """
                    )
                
                rows = cursor.fetchall()
                tables = []
                for row in rows:
                    if isinstance(row, dict):
                        val = row.get("table_name") or row.get("TABLE_NAME")
                        if val is None:
                            val = next(iter(row.values()))
                        tables.append(val)
                    elif isinstance(row, tuple):
                        tables.append(row[0])
                    else:
                        tables.append(str(row))
                return tables
        except Exception as e:
            raise RuntimeError(f"Failed to list tables: {str(e)}")
    
    def select_database(self, db_name: str) -> bool:
        """Switch to a specific database using current connection credentials"""
        if not self.connection_params:
            raise RuntimeError("Must connect to server first with /connect")
            
        # Create a copy of existing params with the new database name
        new_params = self.connection_params.copy()
        new_params["database"] = db_name
        
        # Attempt to connect to the new database
        try:
            if self.db_type in ["mysql", "mariadb"]:
                with mysql.connect(
                    host=new_params["host"],
                    port=int(new_params["port"]),
                    database=new_params["database"],
                    user=new_params["user"],
                    password=new_params["password"],
                    connect_timeout=5,
                ) as conn:
                    with conn.cursor() as cursor:
                        cursor.execute("SELECT VERSION()")
                    self.db_version = cursor.fetchone()[0]
            elif self.db_type == "mssql":
                with pymssql.connect(
                    server=new_params["host"],
                    port=new_params["port"],
                    user=new_params["user"],
                    password=new_params["password"],
                    database=new_params["database"],
                    login_timeout=5
                ) as conn:
                    with conn.cursor() as cursor:
                        cursor.execute("SELECT @@VERSION")
                        row = cursor.fetchone()
                        self.db_version = row[0] if row else "Unknown MSSQL Version"
            elif self.db_type == "oracle":
                dsn = f"{new_params['host']}:{new_params['port']}/{new_params['database']}"
                with oracledb.connect(
                    user=new_params["user"],
                    password=new_params["password"],
                    dsn=dsn
                ) as conn:
                    self.db_version = conn.version
            else:
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

    def create_connection(self) -> Any:
        """Create a new database connection"""
        if not self.connected:
            raise RuntimeError("Database not connected")
            
        if self.db_type in ["mysql", "mariadb"]:
            # Use dictionary=True to mimic RealDictCursor behavior
            # Use DictCursor to mimic RealDictCursor behavior
            return mysql.connect(
                host=self.connection_params["host"],
                port=int(self.connection_params["port"]),
                database=self.connection_params["database"],
                user=self.connection_params["user"],
                password=self.connection_params["password"],
                cursorclass=mysql.cursors.DictCursor
            )
        elif self.db_type == "mssql":
            # pymssql supports as_dict=True
            return pymssql.connect(
                server=self.connection_params["host"],
                port=self.connection_params["port"],
                user=self.connection_params["user"],
                password=self.connection_params["password"],
                database=self.connection_params["database"] or "master",
                as_dict=True
            )
        elif self.db_type == "oracle":
            dsn = f"{self.connection_params['host']}:{self.connection_params['port']}/{self.connection_params['database']}" if self.connection_params['database'] else f"{self.connection_params['host']}:{self.connection_params['port']}"
            return oracledb.connect(
                user=self.connection_params["user"],
                password=self.connection_params["password"],
                dsn=dsn
            )
        else:
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
        
        if self.db_type in ["mysql", "mariadb"]:
            db_uri = f"mysql+mysqlconnector://{username}:{password}@{host}:{port}/{dbname}"
        elif self.db_type == "mssql":
            db_uri = f"mssql+pymssql://{username}:{password}@{host}:{port}/{dbname}"
        elif self.db_type == "oracle":
            db_uri = f"oracle+oracledb://{username}:{password}@{host}:{port}/{dbname}"
        else:
            db_uri = f"postgresql://{username}:{password}@{host}:{port}/{dbname}"
            
        return SQLDatabase.from_uri(db_uri)
    
    def execute_query(self, sql_query: str) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
        """Execute SQL query and return results"""
        if not self.connected:
            raise RuntimeError("Database not connected")
            
        import time
        start_time = time.time()
        try:
            with self.create_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(sql_query)
                    
                    is_select = sql_query.strip().lower().startswith(("select", "with", "show", "describe", "explain"))
                    if is_select:
                        results = cursor.fetchall()
                        elapsed = time.time() - start_time
                        # Convert RealDictRow objects to regular dictionaries
                        dict_results = convert_realdict_to_dict(results)
                        logging.info(f"   [OK] DB Response: {len(dict_results)} rows in {elapsed:.3f}s")
                        return dict_results
                    else:
                        if self.db_type not in ["mysql", "mariadb", "mssql", "oracle"]: # MySQL autocommits usually or handles via connection
                            conn.commit()
                        elapsed = time.time() - start_time
                        logging.info(f"   [OK] Command executed: {cursor.rowcount} rows affected in {elapsed:.3f}s")
                        return {
                            "status": "Command executed successfully", 
                            "rows_affected": cursor.rowcount,
                            "query": sql_query.strip()
                        }
                        
        except Exception as e:
            raise RuntimeError(f"Query execution failed: {str(e)}")

    def get_simplified_schema(self, allowed_tables: Optional[List[str]] = None) -> str:
        if not self.connected:
            raise RuntimeError("Database not connected")
        use_cache = allowed_tables is None or allowed_tables == ["*"]
        key = make_db_cache_key(self.connection_params or {})
        if use_cache:
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
                cursor = conn.cursor()
                if self.db_type in ["mysql", "mariadb"]:
                    cursor.execute(
                        """
                        SELECT table_schema, table_name, column_name, data_type, is_nullable, ordinal_position
                        FROM information_schema.columns
                        WHERE table_schema = %s
                        ORDER BY table_name, ordinal_position
                        """, (self.connection_params["database"],)
                    )
                    cols = cursor.fetchall()
                    
                    cursor.execute(
                        """
                        SELECT table_schema, table_name, column_name
                        FROM information_schema.key_column_usage
                        WHERE constraint_name = 'PRIMARY'
                          AND table_schema = %s
                        """, (self.connection_params["database"],)
                    )
                    pk_rows = cursor.fetchall()
                elif self.db_type == "mssql":
                    cursor.execute(
                        """
                        SELECT TABLE_SCHEMA as table_schema, TABLE_NAME as table_name, COLUMN_NAME as column_name, DATA_TYPE as data_type, IS_NULLABLE as is_nullable, ORDINAL_POSITION as ordinal_position
                        FROM INFORMATION_SCHEMA.COLUMNS
                        ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION
                        """
                    )
                    cols = [dict(r) if hasattr(r, 'keys') else {"table_schema": r[0], "table_name": r[1], "column_name": r[2], "data_type": r[3], "is_nullable": r[4], "ordinal_position": r[5]} for r in cursor.fetchall()]
                    
                    cursor.execute(
                        """
                        SELECT kcu.TABLE_SCHEMA as table_schema, kcu.TABLE_NAME as table_name, kcu.COLUMN_NAME as column_name
                        FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
                        JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu ON tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
                        WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
                        """
                    )
                    pk_rows = [dict(r) if hasattr(r, 'keys') else {"table_schema": r[0], "table_name": r[1], "column_name": r[2]} for r in cursor.fetchall()]
                elif self.db_type == "oracle":
                    cursor.execute(
                        """
                        SELECT owner as table_schema, table_name, column_name, data_type, nullable as is_nullable, column_id as ordinal_position
                        FROM all_tab_columns
                        WHERE owner NOT IN ('SYS', 'SYSTEM', 'XDB', 'WMSYS', 'OJVMSYS', 'CTXSYS', 'ORDSYS', 'ORDDATA', 'MDSYS', 'OLAPSYS')
                        ORDER BY owner, table_name, column_id
                        """
                    )
                    cols_raw = cursor.fetchall()
                    cols = [{"table_schema": r[0], "table_name": r[1], "column_name": r[2], "data_type": r[3], "is_nullable": 'YES' if r[4] == 'Y' else 'NO', "ordinal_position": r[5]} for r in cols_raw]
                    
                    cursor.execute(
                        """
                        SELECT cols.owner as table_schema, cols.table_name, cols.column_name
                        FROM all_constraints cons, all_cons_columns cols
                        WHERE cons.constraint_type = 'P'
                        AND cons.constraint_name = cols.constraint_name
                        AND cons.owner = cols.owner
                        AND cons.owner NOT IN ('SYS', 'SYSTEM', 'XDB', 'WMSYS', 'OJVMSYS', 'CTXSYS', 'ORDSYS', 'ORDDATA', 'MDSYS', 'OLAPSYS')
                        """
                    )
                    pk_raw = cursor.fetchall()
                    pk_rows = [{"table_schema": r[0], "table_name": r[1], "column_name": r[2]} for r in pk_raw]
                else:
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
                cursor.close()
        except Exception as e:
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
        
        # Prepare allowed tables set if filtering is enabled
        allowed_lower = None
        if allowed_tables is not None and allowed_tables != ["*"]:
            allowed_lower = {t.lower() for t in allowed_tables}
            
        for (schema, table), columns in tables.items():
            # If allowed_tables filter is active, skip any tables not in the list
            if allowed_lower is not None and table.lower() not in allowed_lower:
                continue
                
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
        if use_cache:
            try:
                self._schema_cache[key] = {"text": text, "generated_at": datetime.now()}
            except Exception:
                pass
        return text

    def get_schema_dict(self) -> Dict[str, Any]:
        """Fetch database schema as a structured dictionary including foreign keys"""
        if not self.connected:
            raise RuntimeError("Database not connected")
        
        try:
            with self.create_connection() as conn:
                cursor = conn.cursor()
                if self.db_type in ["mysql", "mariadb"]:
                    # Get tables and columns for MariaDB
                    cursor = conn.cursor(cursor=mysql.cursors.DictCursor)
                    cursor.execute(
                        """
                        SELECT table_schema, table_name, column_name, data_type, is_nullable, ordinal_position
                        FROM information_schema.columns
                        WHERE table_schema = %s
                        ORDER BY table_name, ordinal_position
                        """, (self.connection_params["database"],)
                    )
                    cols = cursor.fetchall()
                    
                    # Get primary keys
                    cursor.execute(
                        """
                        SELECT table_schema, table_name, column_name
                        FROM information_schema.key_column_usage
                        WHERE constraint_name = 'PRIMARY'
                          AND table_schema = %s
                        """, (self.connection_params["database"],)
                    )
                    pk_rows = cursor.fetchall()

                    # Get foreign keys (existing)
                    cursor.execute(
                        """
                        SELECT table_name, column_name, referenced_table_name as referred_table, 
                               referenced_table_schema as referred_schema
                        FROM information_schema.key_column_usage
                        WHERE referenced_table_name IS NOT NULL
                          AND table_schema = %s
                        """, (self.connection_params["database"],)
                    )
                    fk_rows = cursor.fetchall()
                    
                    # NEW: Get estimated row counts for MySQL/MariaDB
                    cursor.execute(
                        """
                        SELECT table_schema, table_name, table_rows as row_count
                        FROM information_schema.tables
                        WHERE table_schema = %s
                        """, (self.connection_params["database"],)
                    )
                    count_rows = cursor.fetchall()
                elif self.db_type == "mssql":
                    # Get tables and columns for MSSQL
                    cursor.execute(
                        """
                        SELECT TABLE_SCHEMA as table_schema, TABLE_NAME as table_name, COLUMN_NAME as column_name, DATA_TYPE as data_type, IS_NULLABLE as is_nullable, ORDINAL_POSITION as ordinal_position
                        FROM INFORMATION_SCHEMA.COLUMNS
                        ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION
                        """
                    )
                    cols = [dict(r) if hasattr(r, 'keys') else {"table_schema": r[0], "table_name": r[1], "column_name": r[2], "data_type": r[3], "is_nullable": r[4], "ordinal_position": r[5]} for r in cursor.fetchall()]
                    
                    # Get primary keys
                    cursor.execute(
                        """
                        SELECT kcu.TABLE_SCHEMA as table_schema, kcu.TABLE_NAME as table_name, kcu.COLUMN_NAME as column_name
                        FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
                        JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu ON tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
                        WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
                        """
                    )
                    pk_rows = [dict(r) if hasattr(r, 'keys') else {"table_schema": r[0], "table_name": r[1], "column_name": r[2]} for r in cursor.fetchall()]

                    # Get foreign keys
                    cursor.execute(
                        """
                        SELECT
                            tp.name AS table_name,
                            cp.name AS column_name,
                            tr.name AS referred_table,
                            SCHEMA_NAME(tr.schema_id) AS referred_schema
                        FROM 
                            sys.foreign_keys fk
                        INNER JOIN 
                            sys.tables tp ON fk.parent_object_id = tp.object_id
                        INNER JOIN 
                            sys.tables tr ON fk.referenced_object_id = tr.object_id
                        INNER JOIN 
                            sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id
                        INNER JOIN 
                            sys.columns cp ON fkc.parent_column_id = cp.column_id AND fkc.parent_object_id = cp.object_id
                        """
                    )
                    fk_rows = [dict(r) if hasattr(r, 'keys') else {"table_name": r[0], "column_name": r[1], "referred_table": r[2], "referred_schema": r[3]} for r in cursor.fetchall()]
                    
                    # Get estimated row counts
                    cursor.execute(
                        """
                        SELECT
                            s.name AS table_schema,
                            t.name AS table_name,
                            p.rows AS row_count
                        FROM
                            sys.tables t
                        INNER JOIN
                            sys.indexes i ON t.object_id = i.object_id
                        INNER JOIN
                            sys.partitions p ON i.object_id = p.object_id AND i.index_id = p.index_id
                        INNER JOIN 
                            sys.schemas s ON t.schema_id = s.schema_id
                        WHERE
                            t.is_ms_shipped = 0 AND i.type IN (0,1)
                        """
                    )
                    count_rows = [dict(r) if hasattr(r, 'keys') else {"table_schema": r[0], "table_name": r[1], "row_count": r[2]} for r in cursor.fetchall()]
                elif self.db_type == "oracle":
                    # Get tables and columns for Oracle
                    cursor.execute(
                        """
                        SELECT owner as table_schema, table_name, column_name, data_type, nullable as is_nullable, column_id as ordinal_position
                        FROM all_tab_columns
                        WHERE owner NOT IN ('SYS', 'SYSTEM', 'XDB', 'WMSYS', 'OJVMSYS', 'CTXSYS', 'ORDSYS', 'ORDDATA', 'MDSYS', 'OLAPSYS')
                        ORDER BY owner, table_name, column_id
                        """
                    )
                    cols_raw = cursor.fetchall()
                    cols = [{"table_schema": r[0], "table_name": r[1], "column_name": r[2], "data_type": r[3], "is_nullable": 'YES' if r[4] == 'Y' else 'NO', "ordinal_position": r[5]} for r in cols_raw]
                    
                    # Get primary keys
                    cursor.execute(
                        """
                        SELECT cols.owner as table_schema, cols.table_name, cols.column_name
                        FROM all_constraints cons, all_cons_columns cols
                        WHERE cons.constraint_type = 'P'
                        AND cons.constraint_name = cols.constraint_name
                        AND cons.owner = cols.owner
                        AND cons.owner NOT IN ('SYS', 'SYSTEM', 'XDB', 'WMSYS', 'OJVMSYS', 'CTXSYS', 'ORDSYS', 'ORDDATA', 'MDSYS', 'OLAPSYS')
                        """
                    )
                    pk_raw = cursor.fetchall()
                    pk_rows = [{"table_schema": r[0], "table_name": r[1], "column_name": r[2]} for r in pk_raw]

                    # Get foreign keys
                    cursor.execute(
                        """
                        SELECT a.table_name, a.column_name, c_pk.table_name as referred_table, c_pk.owner as referred_schema
                        FROM all_cons_columns a
                        JOIN all_constraints c ON a.owner = c.owner AND a.constraint_name = c.constraint_name
                        JOIN all_constraints c_pk ON c.r_owner = c_pk.owner AND c.r_constraint_name = c_pk.constraint_name
                        WHERE c.constraint_type = 'R'
                        AND a.owner NOT IN ('SYS', 'SYSTEM', 'XDB', 'WMSYS', 'OJVMSYS', 'CTXSYS', 'ORDSYS', 'ORDDATA', 'MDSYS', 'OLAPSYS')
                        """
                    )
                    fk_raw = cursor.fetchall()
                    fk_rows = [{"table_name": r[0], "column_name": r[1], "referred_table": r[2], "referred_schema": r[3]} for r in fk_raw]
                    
                    # Get estimated row counts
                    cursor.execute(
                        """
                        SELECT owner as table_schema, table_name, num_rows as row_count
                        FROM all_tables
                        WHERE owner NOT IN ('SYS', 'SYSTEM', 'XDB', 'WMSYS', 'OJVMSYS', 'CTXSYS', 'ORDSYS', 'ORDDATA', 'MDSYS', 'OLAPSYS')
                        AND num_rows IS NOT NULL
                        """
                    )
                    count_raw = cursor.fetchall()
                    count_rows = [{"table_schema": r[0], "table_name": r[1], "row_count": r[2]} for r in count_raw]
                else:
                    # Get tables and columns for PostgreSQL
                    cursor.execute(
                        """
                        SELECT table_schema, table_name, column_name, data_type, is_nullable, ordinal_position
                        FROM information_schema.columns
                        WHERE table_schema NOT IN ('pg_catalog','information_schema')
                        ORDER BY table_schema, table_name, ordinal_position
                        """
                    )
                    cols = cursor.fetchall()
                    
                    # Get primary keys
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

                    # Get foreign keys
                    cursor.execute(
                        """
                        SELECT kcu.table_name, kcu.column_name, 
                               ccu.table_name AS referred_table,
                               ccu.table_schema AS referred_schema
                        FROM information_schema.table_constraints AS tc 
                        JOIN information_schema.key_column_usage AS kcu
                           ON tc.constraint_name = kcu.constraint_name
                          AND tc.table_schema = kcu.table_schema
                        JOIN information_schema.constraint_column_usage AS ccu
                           ON ccu.constraint_name = tc.constraint_name
                        WHERE tc.constraint_type = 'FOREIGN KEY'
                           AND tc.table_schema NOT IN ('pg_catalog','information_schema');
                        """
                    )
                    fk_rows = cursor.fetchall()

                    # NEW: Get estimated row counts for PostgreSQL
                    cursor.execute(
                        """
                        SELECT n.nspname AS table_schema, c.relname AS table_name, c.reltuples AS row_count
                        FROM pg_class c
                        JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE c.relkind = 'r' 
                          AND n.nspname NOT IN ('pg_catalog','information_schema')
                        """
                    )
                    count_rows = cursor.fetchall()
                cursor.close()
                
            pk_set = set()
            for r in pk_rows:
                pk_set.add((r["table_schema"] if "table_schema" in r else self.connection_params["database"], 
                           r["table_name"], r["column_name"]))
                
            # Organize columns by table
            tables_data = {}
            for r in cols:
                schema_name = r["table_schema"]
                table_name = r["table_name"]
                key = (schema_name, table_name)
                
                if key not in tables_data:
                    tables_data[key] = {
                        "name": table_name,
                        "schema": schema_name,
                        "columns": [],
                        "foreign_keys": []
                    }
                
                column_info = {
                    "name": r["column_name"],
                    "type": r["data_type"],
                    "nullable": r["is_nullable"] == "YES",
                    "is_primary_key": (schema_name, table_name, r["column_name"]) in pk_set
                }
                tables_data[key]["columns"].append(column_info)

            # Add row counts
            counts_map = {}
            for r in count_rows:
                schema_name = r.get("table_schema") or self.connection_params["database"]
                counts_map[(schema_name, r["table_name"])] = int(r["row_count"])
            
            for key in tables_data:
                tables_data[key]["estimated_rows"] = counts_map.get(key, 0)

            # Add foreign keys
            for r in fk_rows:
                schema_name = r.get("table_schema") or self.connection_params["database"]
                table_name = r["table_name"]
                key = (schema_name, table_name)
                
                if key in tables_data:
                    tables_data[key]["foreign_keys"].append({
                        "column": r["column_name"],
                        "referred_table": r["referred_table"],
                        "referred_schema": r.get("referred_schema") or schema_name
                    })
                
            return {
                "database": self.connection_params["database"],
                "tables": list(tables_data.values())
            }
        except Exception as e:
            print(f"Failed to generate schema dict: {e}")
            return {"error": str(e), "database": self.connection_params.get("database"), "tables": []}