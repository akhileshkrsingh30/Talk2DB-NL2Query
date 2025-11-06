import re
from typing import List

def extract_sql_queries(text: str) -> List[str]:
    """Extract SQL queries from text"""
    if not text:
        return []
    
    queries = []
    
    # Try different patterns to extract SQL
    queries += [q.strip() for q in re.findall(r'```sql\n(.*?)\n```', text, re.DOTALL)]
    queries += [q.strip() for q in re.findall(r'```\n(.*?)\n```', text, re.DOTALL)]
    queries += [q.strip() for q in re.findall(r'SQLQuery:\s*(.*?)(?:\n|$)', text, re.DOTALL)]
    
    # If no queries found with patterns, try to split by semicolons
    if not queries:
        parts = [p.strip() for p in text.split(";")]
        queries = [p for p in parts if p and any(
            k in p.upper() for k in ["SELECT", "INSERT", "UPDATE", "DELETE", "CREATE"]
        )]
    
    return queries