from typing import Dict, Any
from config import settings

class BillingService:
    def __init__(self):
        # Rates per single token
        self.input_rate = settings.price_input_1m / 1_000_000
        self.output_rate = settings.price_output_1m / 1_000_000

    def calculate_cost(self, input_tokens: int, output_tokens: int, user_id: str = None, session_id: str = None) -> Dict[str, Any]:
        """
        Calculate the cost of a request based on token usage.
        Returns a dictionary with cost details.
        """
        input_cost = input_tokens * self.input_rate
        output_cost = output_tokens * self.output_rate
        total_cost = input_cost + output_cost

        return {
            "user_id": user_id,
            "session_id": session_id,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "input_cost": round(input_cost, 6),
            "output_cost": round(output_cost, 6),
            "total_cost": round(total_cost, 6),
            "currency": "USD"
        }
