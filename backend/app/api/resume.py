import json
import uuid
from pathlib import Path

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db import get_db
from app.models import Resume, ResumeBulletNote, User
from app.schemas.resume import (
    BulletNoteCreate,
    BulletNoteOut,
    BulletNoteUpdate,
    ParseResult,
    ProfileUpdate,
    ResumeOut,
    ResumeReviewOut,
    ReviewBulletCreate,
    ReviewBulletUpdate,
    ReviewItemCreate,
    ReviewItemUpdate,
)
from app.services.billing import assert_platform_allowed
from app.services.resume_review import (
    add_review_bullet,
    add_review_item,
    assemble_review_tree,
    delete_review_bullet,
    delete_review_item,
    dump_layout,
    hydrate_layout,
    parse_layout,
    rename_review_item,
    update_review_bullet,
    validate_note_payload,
)
from app.services.resume_service import build_profile, extract_text

router = APIRouter(prefix="/api/resume", tags=["resume"])

UPLOAD_DIR = Path(__file__).resolve().parents[2] / "data" / "uploads"
ALLOWED_EXT = {".pdf"}


def _to_out(r: Resume) -> ResumeOut:
    stored = (getattr(r, "stored_path", None) or "").strip()
    has_file = bool(stored) and (UPLOAD_DIR / Path(stored).name).is_file()
    return ResumeOut(
        id=r.id,
        filename=r.filename,
        profile=json.loads(r.profile_json) if r.profile_json else None,
        analysis=json.loads(r.analysis_json) if getattr(r, "analysis_json", None) else None,
        has_file=has_file,
        created_at=r.created_at,
    )


def _get_owned_resume(db: Session, resume_id: int, user_id: int) -> Resume:
    resume = db.get(Resume, resume_id)
    if resume is None or resume.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="简历不存在")
    return resume


@router.get("", response_model=list[ResumeOut])
def list_resumes(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ResumeOut]:
    resumes = db.scalars(
        select(Resume)
        .where(Resume.user_id == current_user.id)
        .order_by(Resume.created_at.desc())
    ).all()
    return [_to_out(r) for r in resumes]


@router.get("/{resume_id}", response_model=ResumeOut)
def get_resume(
    resume_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ResumeOut:
    return _to_out(_get_owned_resume(db, resume_id, current_user.id))


@router.post("/upload", response_model=ResumeOut, status_code=status.HTTP_201_CREATED)
def upload_resume(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ResumeOut:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXT:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="仅支持 PDF 文件"
        )
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件为空")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    path = UPLOAD_DIR / f"{uuid.uuid4().hex}{suffix}"
    path.write_bytes(content)
    try:
        raw_text = extract_text(path)
    except Exception:
        path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="PDF 解析失败，请确认是文字版 PDF（不是扫描件/图片）",
        )
    if not raw_text:
        path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="PDF 中没有提取到文字，请确认是文字版 PDF（不是扫描件/图片）",
        )

    resume = Resume(
        user_id=current_user.id,
        filename=file.filename,
        stored_path=path.name,
        raw_text=raw_text,
    )
    db.add(resume)
    db.commit()
    db.refresh(resume)
    return _to_out(resume)


@router.post("/{resume_id}/parse", response_model=ParseResult)
def parse_resume(
    resume_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ParseResult:
    resume = _get_owned_resume(db, resume_id, current_user.id)
    assert_platform_allowed(db, current_user)
    try:
        profile = build_profile(resume.raw_text)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="AI 画像生成失败，请稍后重试"
        )
    resume.profile_json = json.dumps(profile, ensure_ascii=False)
    db.commit()
    db.refresh(resume)
    return ParseResult(resume=_to_out(resume), profile=profile)


@router.put("/{resume_id}/profile", response_model=ResumeOut)
def update_profile(
    resume_id: int,
    payload: ProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ResumeOut:
    resume = _get_owned_resume(db, resume_id, current_user.id)
    resume.profile_json = json.dumps(payload.profile, ensure_ascii=False)
    db.commit()
    db.refresh(resume)
    return _to_out(resume)


@router.delete("/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_resume(
    resume_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    resume = _get_owned_resume(db, resume_id, current_user.id)
    # 若仍有关联面试会话则拒绝删除，避免外键/孤儿数据
    from app.models import InterviewSession

    used = db.scalars(
        select(InterviewSession.id).where(InterviewSession.resume_id == resume_id).limit(1)
    ).first()
    if used is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该简历已用于面试，无法删除。可保留并上传新简历。",
        )
    stored = (getattr(resume, "stored_path", None) or "").strip()
    if stored:
        (UPLOAD_DIR / Path(stored).name).unlink(missing_ok=True)
    db.execute(delete(ResumeBulletNote).where(ResumeBulletNote.resume_id == resume_id))
    db.delete(resume)
    db.commit()


@router.get("/{resume_id}/file")
def download_resume_file(
    resume_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """返回原始 PDF（有文件时）；旧简历无文件则 404。"""
    from fastapi.responses import FileResponse

    resume = _get_owned_resume(db, resume_id, current_user.id)
    stored = (getattr(resume, "stored_path", None) or "").strip()
    if not stored:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="该简历没有可预览的 PDF（上传时未保留文件）。可重新上传后再预览。",
        )
    path = UPLOAD_DIR / Path(stored).name
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PDF 文件已丢失，请重新上传")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=resume.filename or path.name,
        content_disposition_type="inline",
    )


@router.get("/{resume_id}/text-preview")
def resume_text_preview(
    resume_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """无 PDF 时的文本预览兜底。"""
    resume = _get_owned_resume(db, resume_id, current_user.id)
    return {
        "resume_id": resume.id,
        "filename": resume.filename,
        "has_file": bool((getattr(resume, "stored_path", None) or "").strip()),
        "text": (resume.raw_text or "")[:20000],
    }


@router.post("/{resume_id}/analyze")
def analyze_resume_api(
    resume_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    from app.services.resume_analysis import analyze_resume

    resume = _get_owned_resume(db, resume_id, current_user.id)
    assert_platform_allowed(db, current_user)
    profile = json.loads(resume.profile_json) if resume.profile_json else None
    try:
        result = analyze_resume(resume.raw_text or "", profile)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="简历分析失败，请稍后重试"
        )
    resume.analysis_json = json.dumps(result, ensure_ascii=False)
    db.commit()
    db.refresh(resume)
    return {"resume_id": resume.id, "analysis": result}


@router.get("/{resume_id}/analyze/export")
def export_resume_analysis(
    resume_id: int,
    format: str = "docx",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from fastapi.responses import Response

    from app.services.resume_analysis_export import build_analysis_docx, build_analysis_pdf

    resume = _get_owned_resume(db, resume_id, current_user.id)
    if not resume.analysis_json:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="尚未生成分析报告，请先分析")
    analysis = json.loads(resume.analysis_json)
    meta = {
        "filename": resume.filename,
        "created_at": resume.created_at.strftime("%Y-%m-%d %H:%M") if resume.created_at else "",
    }
    fmt = (format or "docx").lower()
    if fmt == "pdf":
        buf = build_analysis_pdf(analysis, meta)
        return Response(
            content=buf,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="resume_analysis_{resume_id}.pdf"'
            },
        )
    buf = build_analysis_docx(analysis, meta)
    return Response(
        content=buf,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f'attachment; filename="resume_analysis_{resume_id}.docx"'
        },
    )


def _note_row_dict(row: ResumeBulletNote) -> dict:
    return {
        "id": row.id,
        "kind": row.kind,
        "question": row.question or "",
        "answer": row.answer or "",
        "body": row.body or "",
        "section_type": row.section_type,
        "item_key": row.item_key,
        "bullet_key": row.bullet_key,
        "item_label": row.item_label or "",
        "bullet_text": row.bullet_text or "",
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _get_owned_note(
    db: Session, resume_id: int, note_id: int, user_id: int
) -> tuple[Resume, ResumeBulletNote]:
    resume = _get_owned_resume(db, resume_id, user_id)
    note = db.get(ResumeBulletNote, note_id)
    if note is None or note.resume_id != resume.id or note.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="笔记不存在")
    return resume, note


def _review_notes(db: Session, resume_id: int, user_id: int) -> list[dict]:
    notes = db.scalars(
        select(ResumeBulletNote)
        .where(
            ResumeBulletNote.resume_id == resume_id,
            ResumeBulletNote.user_id == user_id,
        )
        .order_by(ResumeBulletNote.created_at.asc(), ResumeBulletNote.id.asc())
    ).all()
    return [_note_row_dict(n) for n in notes]


def _review_out(resume: Resume, profile: dict | None, notes: list[dict]) -> ResumeReviewOut:
    customized = bool((resume.review_tree_json or "").strip())
    if customized:
        tree = hydrate_layout(json.loads(resume.review_tree_json or "{}"), notes, profile)
    else:
        tree = assemble_review_tree(profile, notes, raw_text=resume.raw_text)
    return ResumeReviewOut(
        resume_id=resume.id,
        filename=resume.filename,
        has_profile=bool(profile),
        layout_customized=customized,
        **tree,
    )


def _load_mutable_layout(resume: Resume, profile: dict | None, notes: list[dict]) -> dict:
    if (resume.review_tree_json or "").strip():
        return parse_layout(json.loads(resume.review_tree_json or "{}"))
    tree = assemble_review_tree(profile, notes, raw_text=resume.raw_text)
    return parse_layout(dump_layout(tree))


def _save_layout_and_out(
    db: Session, resume: Resume, profile: dict | None, notes: list[dict], layout: dict
) -> ResumeReviewOut:
    resume.review_tree_json = json.dumps(parse_layout(layout), ensure_ascii=False)
    db.commit()
    db.refresh(resume)
    return _review_out(resume, profile, notes)


@router.get("/{resume_id}/review", response_model=ResumeReviewOut)
def get_resume_review(
    resume_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ResumeReviewOut:
    resume = _get_owned_resume(db, resume_id, current_user.id)
    profile = json.loads(resume.profile_json) if resume.profile_json else None
    return _review_out(resume, profile, _review_notes(db, resume.id, current_user.id))


@router.post("/{resume_id}/review/items", response_model=ResumeReviewOut)
def create_review_item(
    resume_id: int,
    payload: ReviewItemCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ResumeReviewOut:
    resume = _get_owned_resume(db, resume_id, current_user.id)
    profile = json.loads(resume.profile_json) if resume.profile_json else None
    notes = _review_notes(db, resume.id, current_user.id)
    layout = _load_mutable_layout(resume, profile, notes)
    try:
        add_review_item(
            layout,
            title=payload.title,
            section=payload.section,
            parent_item_key=(payload.parent_item_key or "").strip() or None,
            subtitle=payload.subtitle,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="目标经历不存在") from exc
    return _save_layout_and_out(db, resume, profile, notes, layout)


@router.patch("/{resume_id}/review/items/{item_key}", response_model=ResumeReviewOut)
def update_review_item(
    resume_id: int,
    item_key: str,
    payload: ReviewItemUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ResumeReviewOut:
    resume = _get_owned_resume(db, resume_id, current_user.id)
    profile = json.loads(resume.profile_json) if resume.profile_json else None
    notes = _review_notes(db, resume.id, current_user.id)
    layout = _load_mutable_layout(resume, profile, notes)
    try:
        rename_review_item(layout, item_key, title=payload.title, subtitle=payload.subtitle)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在") from exc
    return _save_layout_and_out(db, resume, profile, notes, layout)


@router.delete("/{resume_id}/review/items/{item_key}", response_model=ResumeReviewOut)
def remove_review_item(
    resume_id: int,
    item_key: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ResumeReviewOut:
    resume = _get_owned_resume(db, resume_id, current_user.id)
    profile = json.loads(resume.profile_json) if resume.profile_json else None
    notes = _review_notes(db, resume.id, current_user.id)
    layout = _load_mutable_layout(resume, profile, notes)
    try:
        delete_review_item(layout, item_key)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在") from exc
    return _save_layout_and_out(db, resume, profile, notes, layout)


@router.post("/{resume_id}/review/items/{item_key}/bullets", response_model=ResumeReviewOut)
def create_review_bullet(
    resume_id: int,
    item_key: str,
    payload: ReviewBulletCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ResumeReviewOut:
    resume = _get_owned_resume(db, resume_id, current_user.id)
    profile = json.loads(resume.profile_json) if resume.profile_json else None
    notes = _review_notes(db, resume.id, current_user.id)
    layout = _load_mutable_layout(resume, profile, notes)
    try:
        add_review_bullet(layout, item_key, payload.text)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在") from exc
    return _save_layout_and_out(db, resume, profile, notes, layout)


@router.patch(
    "/{resume_id}/review/items/{item_key}/bullets/{bullet_key}",
    response_model=ResumeReviewOut,
)
def edit_review_bullet(
    resume_id: int,
    item_key: str,
    bullet_key: str,
    payload: ReviewBulletUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ResumeReviewOut:
    resume = _get_owned_resume(db, resume_id, current_user.id)
    profile = json.loads(resume.profile_json) if resume.profile_json else None
    notes = _review_notes(db, resume.id, current_user.id)
    layout = _load_mutable_layout(resume, profile, notes)
    try:
        update_review_bullet(layout, item_key, bullet_key, payload.text)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="bullet 不存在") from exc
    return _save_layout_and_out(db, resume, profile, notes, layout)


@router.delete(
    "/{resume_id}/review/items/{item_key}/bullets/{bullet_key}",
    response_model=ResumeReviewOut,
)
def remove_review_bullet(
    resume_id: int,
    item_key: str,
    bullet_key: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ResumeReviewOut:
    resume = _get_owned_resume(db, resume_id, current_user.id)
    profile = json.loads(resume.profile_json) if resume.profile_json else None
    notes = _review_notes(db, resume.id, current_user.id)
    layout = _load_mutable_layout(resume, profile, notes)
    try:
        delete_review_bullet(layout, item_key, bullet_key)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="bullet 不存在") from exc
    return _save_layout_and_out(db, resume, profile, notes, layout)


@router.post(
    "/{resume_id}/review/notes",
    response_model=BulletNoteOut,
    status_code=status.HTTP_201_CREATED,
)
def create_resume_review_note(
    resume_id: int,
    payload: BulletNoteCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ResumeBulletNote:
    resume = _get_owned_resume(db, resume_id, current_user.id)
    item_key = (payload.item_key or "").strip()
    bullet_key = (payload.bullet_key or "").strip()
    if not item_key or not bullet_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="缺少挂载位置")
    try:
        question, answer, body = validate_note_payload(
            payload.kind, payload.question, payload.answer, payload.body
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    now = datetime.now(timezone.utc)
    row = ResumeBulletNote(
        resume_id=resume.id,
        user_id=current_user.id,
        section_type=payload.section_type,
        item_key=item_key,
        bullet_key=bullet_key,
        item_label=(payload.item_label or "").strip()[:256],
        bullet_text=(payload.bullet_text or "").strip()[:2000],
        kind=payload.kind,
        question=question,
        answer=answer,
        body=body,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.put("/{resume_id}/review/notes/{note_id}", response_model=BulletNoteOut)
def update_resume_review_note(
    resume_id: int,
    note_id: int,
    payload: BulletNoteUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ResumeBulletNote:
    _resume, row = _get_owned_note(db, resume_id, note_id, current_user.id)
    question = payload.question if payload.question is not None else row.question
    answer = payload.answer if payload.answer is not None else row.answer
    body = payload.body if payload.body is not None else row.body
    try:
        question, answer, body = validate_note_payload(row.kind, question, answer, body)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    row.question = question
    row.answer = answer
    row.body = body
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/{resume_id}/review/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_resume_review_note(
    resume_id: int,
    note_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    _resume, row = _get_owned_note(db, resume_id, note_id, current_user.id)
    db.delete(row)
    db.commit()
