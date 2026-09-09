import re
from typing import List

def extract_sql_queries(text: str) -> List[str]:
    """Extract SQL queries from LLM output.

    Handles:
    - Fenced code blocks (```sql ... ``` or ``` ... ```)
    - Plain SQL prefixed with 'SQL Query:' or 'SQLQuery:'
    - Multiple statements separated by semicolons
    - Bare SQL with no wrapper (most common with raw-output prompts)
    - CTEs (WITH ... SELECT) with no trailing semicolon
    """
    if not text or not text.strip():
        return []

    text = text.strip()
    queries = []

    # 1. Fenced ```sql ... ``` blocks (flexible whitespace)
    queries += [q.strip() for q in re.findall(r'```sql\s*(.*?)```', text, re.DOTALL | re.IGNORECASE)]
    # 2. Fenced ``` ... ``` blocks (generic)
    if not queries:
        queries += [q.strip() for q in re.findall(r'```\s*(.*?)```', text, re.DOTALL)]
    # 3. Labelled output: "SQL Query:" or "SQLQuery:"
    if not queries:
        queries += [q.strip() for q in re.findall(r'(?:SQL\s*Query\s*:)\s*(.*?)(?:\n\n|$)', text, re.DOTALL | re.IGNORECASE)]

    # 4. Semicolon-separated statements
    if not queries:
        parts = [p.strip() for p in text.split(";")]
        queries = [
            p for p in parts
            if p and any(k in p.upper() for k in ["SELECT", "INSERT", "UPDATE", "DELETE", "CREATE", "WITH", "SHOW", "EXEC"])
        ]

    # 5. Last resort: treat the entire response as one SQL statement
    if not queries:
        sql_keywords = ["SELECT", "INSERT", "UPDATE", "DELETE", "CREATE", "WITH", "MERGE", "DROP", "ALTER", "SHOW", "EXEC"]
        upper = text.upper().lstrip()
        if any(upper.startswith(k) for k in sql_keywords):
            queries = [text]

    # Clean up: remove any leading reasoning/conversational text before the SQL keyword, strip semicolons, and deduplicate
    sql_start_regex = re.compile(r'\b(WITH|SELECT|INSERT|UPDATE|DELETE|CREATE|SHOW|EXEC|EXECUTE|DECLARE)\b', re.IGNORECASE)
    cleaned = []
    seen = set()
    for q in queries:
        q = q.strip().rstrip(";").strip()
        match = sql_start_regex.search(q)
        if match:
            q = q[match.start():]
        q = q.strip().rstrip(";").strip()
        
        normalized = re.sub(r'\s+', ' ', q.lower())
        if q and normalized not in seen:
            seen.add(normalized)
            cleaned.append(q)

    return cleaned