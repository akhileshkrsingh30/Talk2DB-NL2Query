import re
from typing import List

def extract_sql_queries(text: str) -> List[str]:
    """Extract SQL queries from text with stricter validation to avoid executing conversational filler."""
    if not text:
        return []
    
    queries = []
    
    # 1. Try to find markdown blocks (highest confidence)
    queries += [q.strip() for q in re.findall(r'```sql\s*\n(.*?)\n```', text, re.DOTALL | re.IGNORECASE)]
    
    # 2. Try to find generic code blocks
    if not queries:
        queries += [q.strip() for q in re.findall(r'```\s*\n(.*?)\n```', text, re.DOTALL)]
    
    # 3. Try to find "SQLQuery:" prefix
    if not queries:
        queries += [q.strip() for q in re.findall(r'SQLQuery:\s*(.*?)(?:\n|$)', text, re.DOTALL | re.IGNORECASE)]
    
    # 4. If still no queries, try to parse segments split by semicolons but validate first word
    if not queries:
        # Define common starting keywords for valid SQL operations
        valid_start_keywords = {"SELECT", "WITH", "INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP", "TRUNCATE"}
        
        parts = [p.strip() for p in text.split(";")]
        for part in parts:
            if not part:
                continue
            
            # Remove line comments to find the actual first word
            clean_part = re.sub(r'--.*$', '', part, flags=re.MULTILINE).strip()
            
            # Find the first word ignoring numbers and special characters like (
            first_word_match = re.search(r'^\s*([A-Z]+)', clean_part, re.IGNORECASE)
            if first_word_match:
                first_word = first_word_match.group(1).upper()
                if first_word in valid_start_keywords:
                    queries.append(part)
                    
    return queries