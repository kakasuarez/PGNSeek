"""
app/api/schemas.py

Shared API request/response shapes.
"""

from typing import Optional

from pydantic import BaseModel


class ErrorDetail(BaseModel):
    error: str                    # machine-readable code e.g. "query_parse_error"
    message: str                  # human-readable explanation
    detail: Optional[dict] = None # extra context (raw query, field name, etc.)
