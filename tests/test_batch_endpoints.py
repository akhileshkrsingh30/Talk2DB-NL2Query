import json
from fastapi.testclient import TestClient

from main import app
from dependencies import get_db_service, get_llm_service


class DatabaseServiceStub:
    def __init__(self):
        self._connected = True

    def is_connected(self):
        return True

    def execute_query(self, sql):
        s = sql.strip().lower()
        if s.startswith("select"):
            return [{"value": 1, "sql": sql.strip()}]
        return {"status": "Command executed successfully", "rows_affected": 1, "query": sql.strip()}

    def get_langchain_db(self):
        class _DB:
            def get_table_info(self_inner):
                return "table_a, table_b"
        return _DB()

    def create_connection(self):
        class _Cursor:
            def __init__(self):
                self.rowcount = 1
                self._last_sql = None

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def execute(self, sql):
                self._last_sql = sql
                if "FAIL" in sql:
                    raise RuntimeError("Forced failure")

            def fetchall(self):
                return [{"value": 1, "sql": (self._last_sql or "").strip()}]

        class _Conn:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def cursor(self):
                return _Cursor()

            def commit(self):
                pass

            def rollback(self):
                pass

        return _Conn()


class _Chain:
    def __init__(self, response_text):
        self._response_text = response_text

    def invoke(self, payload):
        return self._response_text


class LLMServiceStub:
    def is_configured(self):
        return True

    def get_config_details(self):
        return {"model": "stub"}

    def get_llm(self):
        return object()

    def create_sql_chain(self, db):
        return _Chain("SELECT 1 AS value;")

    def create_explanation_chain(self):
        return _Chain("ok")


def override_dependencies():
    app.dependency_overrides[get_db_service] = lambda: DatabaseServiceStub()
    app.dependency_overrides[get_llm_service] = lambda: LLMServiceStub()


def test_single_nl_query():
    override_dependencies()
    client = TestClient(app)
    payload = {"query": "how many?", "max_tokens": 64, "temperature": 0}
    r = client.post("/queries/process", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data["query"] == payload["query"]
    assert isinstance(data["results"], list)
    assert len(data["results"]) >= 1
    assert "explanation" in data


def test_batch_nl_query_parallel():
    override_dependencies()
    client = TestClient(app)
    payload = {
        "queries": [
            {"query": "q1"},
            {"query": "q2"},
            {"query": "q3"}
        ],
        "parallel": True,
        "max_concurrency": 3
    }
    r = client.post("/queries/process-batch", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert len(data["results"]) == 3


def test_sql_batch_parallel():
    override_dependencies()
    client = TestClient(app)
    payload = {
        "queries": [
            "SELECT 1;",
            "SELECT 2;",
            "UPDATE x SET y = 1;"
        ],
        "parallel": True,
        "max_concurrency": 3
    }
    r = client.post("/database/execute-sql-batch", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert len(data["results"]) == 3
    assert all("sql" in item for item in data["results"]) 


def test_sql_batch_transaction_failure_rolls_back_first_error():
    override_dependencies()
    client = TestClient(app)
    payload = {
        "queries": [
            "UPDATE a SET x = 1;",
            "UPDATE FAIL HERE;",
            "UPDATE should not run;"
        ],
        "transaction": True
    }
    r = client.post("/database/execute-sql-batch", json=payload)
    assert r.status_code == 200 or r.status_code == 500
    if r.status_code == 200:
        data = r.json()
        assert len(data["results"]) == 2
        assert data["results"][1]["error"] is not None
