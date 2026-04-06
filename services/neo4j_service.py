from neo4j import GraphDatabase
from typing import Optional, Dict, Any, List
import logging

class Neo4jService:
    def __init__(self):
        self.driver = None
        self.uri = None
        self.user = None
        self.password = None
        self._connected = False

    def connect(self, uri: str, user: str, password: str):
        """Establish Neo4j connection"""
        self.uri = uri
        self.user = user
        self.password = password
        try:
            self.driver = GraphDatabase.driver(uri, auth=(user, password))
            # Verify connectivity
            self.driver.verify_connectivity()
            self._connected = True
            logging.info(f"Connected to Neo4j at {uri}")
        except Exception as e:
            self._connected = False
            logging.error(f"Failed to connect to Neo4j: {e}")
            raise e

    def is_connected(self) -> bool:
        return self._connected

    def disconnect(self):
        if self.driver:
            self.driver.close()
            self._connected = False

    def schema_exists(self, db_name: str) -> bool:
        """Check if a schema for the given database exists in Neo4j"""
        if not self._connected:
            return False
            
        with self.driver.session(database="neo4j") as session:
            result = session.run(
                "MATCH (db:Database {name: $db_name})-[:HAS_SCHEMA]->() RETURN count(*) > 0 as exists",
                db_name=db_name
            ).single()
            return result["exists"] if result else False

    def push_schema(self, db_name: str, schema_dict: Dict[str, Any]):
        """Push database schema to Neo4j"""
        if not self._connected:
            raise RuntimeError("Neo4j service not connected")

        with self.driver.session(database="neo4j") as session:
            session.execute_write(self._create_schema_graph, db_name, schema_dict)

    @staticmethod
    def _create_schema_graph(tx, db_name: str, schema_dict: Dict[str, Any]):
        """Create the graph in Neo4j with strict database isolation"""
        # 1. Create Database node
        tx.run("MERGE (db:Database {name: $db_name})", db_name=db_name)
        
        tables = schema_dict.get("tables", [])
        if not tables:
            return

        # 2. Bulk create Schemas (isolated by db_name)
        schemas = list(set(t.get("schema", "public") for t in tables))
        schema_params = [{"name": s, "full_name": f"{db_name}.{s}"} for s in schemas]
        
        tx.run("""
            UNWIND $schemas as s_data
            MATCH (db:Database {name: $db_name})
            MERGE (s:Schema {full_name: s_data.full_name})
            SET s.name = s_data.name
            MERGE (db)-[:HAS_SCHEMA]->(s)
        """, db_name=db_name, schemas=schema_params)

        # 3. Bulk create Tables (isolated by db_name)
        table_params = []
        for t in tables:
            s_name = t.get("schema", "public")
            table_params.append({
                "schema_full_name": f"{db_name}.{s_name}",
                "table_name": t["name"],
                "full_name": f"{db_name}.{s_name}.{t['name']}"
            })
        
        tx.run("""
            UNWIND $tables as t_data
            MATCH (s:Schema {full_name: t_data.schema_full_name})
            MERGE (t:Table {full_name: t_data.full_name})
            SET t.name = t_data.table_name
            MERGE (s)-[:HAS_TABLE]->(t)
        """, tables=table_params)

        # 4. Bulk create Columns (isolated by db_name)
        column_params = []
        for t in tables:
            s_name = t.get("schema", "public")
            t_full_name = f"{db_name}.{s_name}.{t['name']}"
            for col in t.get("columns", []):
                column_params.append({
                    "table_full_name": t_full_name,
                    "col_name": col["name"],
                    "col_full_name": f"{t_full_name}.{col['name']}",
                    "col_type": col.get("type"),
                    "nullable": col.get("nullable")
                })
        
        for i in range(0, len(column_params), 1000):
            batch = column_params[i:i+1000]
            tx.run("""
                UNWIND $cols as c_data
                MATCH (t:Table {full_name: c_data.table_full_name})
                MERGE (c:Column {full_name: c_data.col_full_name})
                SET c.name = c_data.col_name, 
                    c.type = c_data.col_type, 
                    c.nullable = c_data.nullable
                MERGE (t)-[:HAS_COLUMN]->(c)
            """, cols=batch)

        # 5. Bulk create Foreign Keys (isolated by db_name)
        fk_params = []
        for t in tables:
            s_name = t.get("schema", "public")
            t_full_name = f"{db_name}.{s_name}.{t['name']}"
            for fk in t.get("foreign_keys", []):
                ref_s = fk.get("referred_schema", s_name)
                fk_params.append({
                    "t1_full_name": t_full_name,
                    "t2_full_name": f"{db_name}.{ref_s}.{fk['referred_table']}"
                })
        
        if fk_params:
            tx.run("""
                UNWIND $fks as fk_data
                MATCH (t1:Table {full_name: fk_data.t1_full_name})
                MATCH (t2:Table {full_name: fk_data.t2_full_name})
                MERGE (t1)-[:REFERENCES]->(t2)
            """, fks=fk_params)

    def find_relevant_schema(self, db_name: str, keywords: List[str]) -> List[Dict[str, Any]]:
        """Find relevant tables and their columns based on keywords, following relationships"""
        if not self._connected:
            return []
            
        with self.driver.session(database="neo4j") as session:
            # Query to find tables that match keywords or have columns matching keywords
            # Then follow REFERENCES relationships (up to 1 hop) to find connected tables
            # Higher weight/ranking could be added, but for now we take distinct set
            # Case-insensitive matching used for robustness
            query = """
            MATCH (db:Database {name: $db_name})-[:HAS_SCHEMA]->(s)-[:HAS_TABLE]->(t:Table)
            WHERE any(kw IN $keywords WHERE toLower(t.name) CONTAINS toLower(kw))
               OR any(kw IN $keywords WHERE EXISTS {
                   MATCH (t)-[:HAS_COLUMN]->(c:Column)
                   WHERE toLower(c.name) CONTAINS toLower(kw)
               })
            
            // Collect matching tables and their immediate neighbors
            OPTIONAL MATCH (t)-[:REFERENCES*0..1]-(related:Table)
            WITH DISTINCT CASE WHEN related IS NOT NULL THEN related ELSE t END as table_node
            
            // Get columns for these tables
            MATCH (table_node)-[:HAS_COLUMN]->(col:Column)
            RETURN table_node.name as table_name, 
                   table_node.full_name as full_name,
                   collect({name: col.name, type: col.type}) as columns
            """
            result = session.run(query, db_name=db_name, keywords=keywords)
            return [record.data() for record in result]
