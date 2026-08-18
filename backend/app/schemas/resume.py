from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ResumeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    profile: dict | None
    analysis: dict | None = None
    has_file: bool = False
    created_at: datetime


class ParseResult(BaseModel):
    resume: ResumeOut
    profile: dict


class ProfileUpdate(BaseModel):
    profile: dict
