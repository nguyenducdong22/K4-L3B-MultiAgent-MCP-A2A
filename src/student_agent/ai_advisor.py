from __future__ import annotations

import json
import os
from typing import Any

import httpx2


class GroqAdvisor:
    """Optional AI Advisor using Groq to augment dispute analysis."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("GROQ_API_KEY")
        self.model = "qwen/qwen3.8-27b"
        self.endpoint = "https://api.groq.com/openai/v1/chat/completions"

    async def advise_dispute(
        self,
        customer_message: str,
        primary_issue: str,
        order_status: str,
        shipment_verdict: str,
        payment_verdict: str,
    ) -> dict[str, Any] | None:
        if not self.api_key or not customer_message:
            return None

        prompt = (
            "You are an e-commerce dispute analyst. Analyze this customer complaint:\n"
            f'Customer message: "{customer_message}"\n'
            f"Case context: primary_issue={primary_issue}, order_status={order_status}, "
            f"shipment={shipment_verdict}, payment={payment_verdict}.\n\n"
            "Output JSON with two arrays:\n"
            '1. "secondary_issues": list of up to 3 short snake_case strings.\n'
            '2. "suggested_actions": list of up to 3 short snake_case actionable steps.\n'
            'Format: {"secondary_issues": [...], "suggested_actions": [...]}'
        )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a precise JSON-only dispute assistant."},
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": 150,
            "temperature": 0.1,
        }

        try:
            async with httpx2.AsyncClient(timeout=0.5) as client:
                resp = await client.post(self.endpoint, headers=headers, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    return json.loads(content)
        except BaseException:
            pass
        return None
