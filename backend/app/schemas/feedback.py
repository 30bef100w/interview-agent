from typing import Literal

from pydantic import BaseModel, Field


class FeedbackCreate(BaseModel):
    source: Literal["contact", "second_session"]
    category: str = Field(min_length=1, max_length=32)
    content: str = Field(min_length=2, max_length=4000)
    contact: str = Field(default="", max_length=256)
    page_url: str = Field(default="", max_length=512)


class FeedbackOut(BaseModel):
    id: int
    ok: bool = True
