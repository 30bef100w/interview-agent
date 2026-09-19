from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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


class BulletNoteCreate(BaseModel):
    section_type: Literal["project", "experience"]
    item_key: str
    bullet_key: str
    item_label: str = ""
    bullet_text: str = ""
    kind: Literal["qa", "note"]
    question: str = ""
    answer: str = ""
    body: str = ""


class BulletNoteUpdate(BaseModel):
    question: str | None = None
    answer: str | None = None
    body: str | None = None


class BulletNoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    question: str = ""
    answer: str = ""
    body: str = ""
    section_type: str = ""
    item_key: str = ""
    bullet_key: str = ""
    item_label: str = ""
    bullet_text: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ReviewBullet(BaseModel):
    bullet_key: str
    text: str
    is_whole: bool = False
    notes: list[BulletNoteOut] = Field(default_factory=list)


class ReviewItem(BaseModel):
    section_type: str
    item_key: str
    title: str
    subtitle: str = ""
    meta: list[str] = Field(default_factory=list)
    scene_tags: list[str] = Field(default_factory=list)
    bullets: list[ReviewBullet] = Field(default_factory=list)
    orphan_notes: list[BulletNoteOut] = Field(default_factory=list)


class ReviewEducation(BaseModel):
    school: str = ""
    degree: str = ""
    major: str = ""
    year: str = ""


class ResumeReviewOut(BaseModel):
    resume_id: int
    filename: str
    has_profile: bool
    name: str = ""
    experience_years: str = ""
    education: list[ReviewEducation] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    experience: list[ReviewItem] = Field(default_factory=list)
    projects: list[ReviewItem] = Field(default_factory=list)
    unmatched_notes: list[BulletNoteOut] = Field(default_factory=list)
