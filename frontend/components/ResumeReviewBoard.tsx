"use client";

import { useMemo, useState } from "react";

import { useToast } from "@/components/Toast";
import { Badge, Card, btnCls } from "@/components/ui";
import { api } from "@/lib/api";

export type BulletNote = {
  id: number;
  kind: "qa" | "note" | string;
  question: string;
  answer: string;
  body: string;
  section_type: string;
  item_key: string;
  bullet_key: string;
  item_label: string;
  bullet_text: string;
  created_at?: string | null;
  updated_at?: string | null;
};

export type ReviewBullet = {
  bullet_key: string;
  text: string;
  is_whole: boolean;
  notes: BulletNote[];
};

export type ReviewItem = {
  section_type: "project" | "experience" | string;
  item_key: string;
  title: string;
  subtitle: string;
  meta: string[];
  scene_tags?: string[];
  bullets: ReviewBullet[];
  orphan_notes: BulletNote[];
  children?: ReviewItem[];
};

export type ResumeReview = {
  resume_id: number;
  filename: string;
  has_profile: boolean;
  layout_customized?: boolean;
  name: string;
  experience_years: string;
  education: { school: string; degree: string; major: string; year: string }[];
  skills: string[];
  experience: ReviewItem[];
  projects: ReviewItem[];
  unmatched_notes: BulletNote[];
};

type Composer = {
  itemKey: string;
  bulletKey: string;
  kind: "qa" | "note";
  question: string;
  answer: string;
  body: string;
  editingId: number | null;
};

type Draft =
  | { kind: "rename"; itemKey: string; title: string; subtitle: string }
  | { kind: "edit-bullet"; itemKey: string; bulletKey: string; text: string };

function noteCount(item: ReviewItem): number {
  return (
    item.bullets.reduce((n, b) => n + b.notes.length, 0) +
    item.orphan_notes.length +
    (item.children ?? []).reduce((n, child) => n + noteCount(child), 0)
  );
}

function itemHasNotes(item: ReviewItem): boolean {
  return noteCount(item) > 0;
}

function composerKey(itemKey: string, bulletKey: string) {
  return `${itemKey}:${bulletKey}`;
}

export default function ResumeReviewBoard({
  review,
  onlyWithNotes,
  onChanged,
}: {
  review: ResumeReview;
  onlyWithNotes: boolean;
  onChanged: () => Promise<void> | void;
}) {
  const toast = useToast();
  const [openKeys, setOpenKeys] = useState<Set<string>>(new Set());
  const [composer, setComposer] = useState<Composer | null>(null);
  const [saving, setSaving] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null);

  const experience = useMemo(
    () => (onlyWithNotes ? review.experience.filter(itemHasNotes) : review.experience),
    [onlyWithNotes, review.experience]
  );
  const projects = useMemo(
    () => (onlyWithNotes ? review.projects.filter(itemHasNotes) : review.projects),
    [onlyWithNotes, review.projects]
  );

  function toggle(itemKey: string, bulletKey: string) {
    const key = composerKey(itemKey, bulletKey);
    setOpenKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function openComposer(
    item: ReviewItem,
    bullet: ReviewBullet,
    kind: "qa" | "note",
    note?: BulletNote
  ) {
    setOpenKeys((prev) => new Set(prev).add(composerKey(item.item_key, bullet.bullet_key)));
    setComposer({
      itemKey: item.item_key,
      bulletKey: bullet.bullet_key,
      kind: note ? (note.kind === "note" ? "note" : "qa") : kind,
      question: note?.question ?? "",
      answer: note?.answer ?? "",
      body: note?.body ?? "",
      editingId: note?.id ?? null,
    });
  }

  async function saveComposer(item: ReviewItem, bullet: ReviewBullet) {
    if (!composer) return;
    setSaving(true);
    try {
      if (composer.editingId) {
        await api(`/api/resume/${review.resume_id}/review/notes/${composer.editingId}`, {
          method: "PUT",
          body: JSON.stringify({
            question: composer.question,
            answer: composer.answer,
            body: composer.body,
          }),
        });
        toast.ok("已更新");
      } else {
        await api(`/api/resume/${review.resume_id}/review/notes`, {
          method: "POST",
          body: JSON.stringify({
            section_type: item.section_type === "experience" ? "experience" : "project",
            item_key: item.item_key,
            bullet_key: bullet.bullet_key,
            item_label: item.title,
            bullet_text: bullet.text,
            kind: composer.kind,
            question: composer.question,
            answer: composer.answer,
            body: composer.body,
          }),
        });
        toast.ok("已保存");
      }
      setComposer(null);
      await onChanged();
    } catch (err) {
      toast.err(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function removeNote(noteId: number) {
    if (!window.confirm("删除这条复习内容？")) return;
    try {
      await api(`/api/resume/${review.resume_id}/review/notes/${noteId}`, {
        method: "DELETE",
      });
      if (composer?.editingId === noteId) setComposer(null);
      toast.ok("已删除");
      await onChanged();
    } catch (err) {
      toast.err(err instanceof Error ? err.message : "删除失败");
    }
  }

  async function mutate(path: string, options: RequestInit, okText: string) {
    setSaving(true);
    try {
      await api(path, options);
      setDraft(null);
      toast.ok(okText);
      await onChanged();
    } catch (err) {
      toast.err(err instanceof Error ? err.message : "操作失败");
    } finally {
      setSaving(false);
    }
  }

  async function addItem(section: "experience" | "projects", parentKey: string | null) {
    const title = window.prompt(
      parentKey || section === "projects" ? "项目名称" : "实习 / 公司名称"
    );
    if (title == null) return;
    if (!title.trim()) {
      toast.err("名称不能为空");
      return;
    }
    await mutate(
      `/api/resume/${review.resume_id}/review/items`,
      {
        method: "POST",
        body: JSON.stringify({
          title: title.trim(),
          section,
          parent_item_key: parentKey,
        }),
      },
      "已添加"
    );
  }

  async function addBullet(itemKey: string) {
    const text = window.prompt("Bullet");
    if (text == null) return;
    if (!text.trim()) {
      toast.err("bullet 不能为空");
      return;
    }
    await mutate(
      `/api/resume/${review.resume_id}/review/items/${itemKey}/bullets`,
      { method: "POST", body: JSON.stringify({ text: text.trim() }) },
      "已添加 bullet"
    );
  }

  async function submitDraft() {
    if (!draft) return;
    if (draft.kind === "rename") {
      await mutate(
        `/api/resume/${review.resume_id}/review/items/${draft.itemKey}`,
        {
          method: "PATCH",
          body: JSON.stringify({ title: draft.title, subtitle: draft.subtitle }),
        },
        "已保存"
      );
    }
    if (draft.kind === "edit-bullet") {
      await mutate(
        `/api/resume/${review.resume_id}/review/items/${draft.itemKey}/bullets/${draft.bulletKey}`,
        { method: "PATCH", body: JSON.stringify({ text: draft.text }) },
        "已保存"
      );
    }
  }

  async function deleteItem(item: ReviewItem) {
    const label = item.section_type === "experience" ? "该实习及其项目" : "该项目";
    if (!window.confirm(`确认删除${label}？关联笔记将移至未匹配。`)) return;
    await mutate(
      `/api/resume/${review.resume_id}/review/items/${item.item_key}`,
      { method: "DELETE" },
      "已删除"
    );
  }

  async function deleteBullet(item: ReviewItem, bullet: ReviewBullet) {
    if (!window.confirm("确认删除该 bullet？关联笔记将保留在本项目下。")) return;
    await mutate(
      `/api/resume/${review.resume_id}/review/items/${item.item_key}/bullets/${bullet.bullet_key}`,
      { method: "DELETE" },
      "已删除 bullet"
    );
  }

  const itemProps = {
    openKeys,
    composer,
    saving,
    draft,
    onlyWithNotes,
    editable: !onlyWithNotes,
    onToggle: toggle,
    onComposer: openComposer,
    onComposerChange: setComposer,
    onSave: saveComposer,
    onDeleteNote: removeNote,
    onDraft: setDraft,
    onSubmitDraft: submitDraft,
    onAddItem: addItem,
    onAddBullet: addBullet,
    onDeleteItem: deleteItem,
    onDeleteBullet: deleteBullet,
  };

  return (
    <div className="flex flex-col gap-4">
      <Card className="overflow-hidden px-8 py-8">
        {review.name ? (
          <h2 className="text-xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
            {review.name}
          </h2>
        ) : null}

        {review.education.length > 0 && (
          <ResumeSection title="教育经历">
            <div className="space-y-2">
              {review.education.map((ed, i) => (
                <div
                  key={`${ed.school}-${i}`}
                  className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 text-sm"
                >
                  <div className="min-w-0">
                    <span className="font-medium text-zinc-900 dark:text-zinc-50">
                      {ed.school || "（学校未标注）"}
                    </span>
                    {(ed.degree || ed.major) && (
                      <span className="text-zinc-600 dark:text-zinc-300">
                        {"  "}
                        {[ed.degree, ed.major].filter(Boolean).join(" · ")}
                      </span>
                    )}
                  </div>
                  {ed.year ? <span className="shrink-0 text-zinc-500">{ed.year}</span> : null}
                </div>
              ))}
            </div>
          </ResumeSection>
        )}

        <ResumeSection title="实习 / 工作经历">
          {experience.length === 0 ? (
            <p className="text-sm text-zinc-400">
              {onlyWithNotes ? "暂无笔记" : "暂无实习经历"}
            </p>
          ) : (
            <div className="space-y-8">
              {experience.map((item) => (
                <ItemBlock key={item.item_key} item={item} nested={false} {...itemProps} />
              ))}
            </div>
          )}
          {!onlyWithNotes && (
            <div className="mt-3">
              <button
                type="button"
                className={btnCls("ghost", "sm")}
                disabled={saving}
                onClick={() => addItem("experience", null)}
              >
                + 添加实习
              </button>
            </div>
          )}
        </ResumeSection>

        <ResumeSection title="项目经历">
          {projects.length === 0 ? (
            <p className="text-sm text-zinc-400">
              {onlyWithNotes ? "暂无笔记" : "暂无项目经历"}
            </p>
          ) : (
            <div className="space-y-8">
              {projects.map((item) => (
                <ItemBlock key={item.item_key} item={item} nested={false} {...itemProps} />
              ))}
            </div>
          )}
          {!onlyWithNotes && (
            <div className="mt-3">
              <button
                type="button"
                className={btnCls("ghost", "sm")}
                disabled={saving}
                onClick={() => addItem("projects", null)}
              >
                + 添加项目
              </button>
            </div>
          )}
        </ResumeSection>
      </Card>

      {review.unmatched_notes.length > 0 && (
        <Card className="px-5 py-4">
          <h3 className="text-sm font-medium text-zinc-800 dark:text-zinc-100">未匹配的旧笔记</h3>
          <p className="mt-1 text-xs text-zinc-400">对应经历已删除或变更，笔记仍保留。</p>
          <div className="mt-3 space-y-2">
            {review.unmatched_notes.map((note) => (
              <NoteCard
                key={note.id}
                note={note}
                onEdit={() => toast.info("原经历已不在列表中，只能删除后重新添加")}
                onDelete={() => removeNote(note.id)}
              />
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

function ResumeSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-8">
      <h3 className="mb-3 border-b border-zinc-200 pb-1.5 text-[13px] font-semibold tracking-wide text-zinc-800 dark:border-zinc-700 dark:text-zinc-100">
        {title}
      </h3>
      {children}
    </section>
  );
}

function ItemBlock({
  item,
  nested,
  openKeys,
  composer,
  saving,
  draft,
  onlyWithNotes,
  editable,
  onToggle,
  onComposer,
  onComposerChange,
  onSave,
  onDeleteNote,
  onDraft,
  onSubmitDraft,
  onAddItem,
  onAddBullet,
  onDeleteItem,
  onDeleteBullet,
}: {
  item: ReviewItem;
  nested: boolean;
  openKeys: Set<string>;
  composer: Composer | null;
  saving: boolean;
  draft: Draft | null;
  onlyWithNotes: boolean;
  editable: boolean;
  onToggle: (itemKey: string, bulletKey: string) => void;
  onComposer: (item: ReviewItem, bullet: ReviewBullet, kind: "qa" | "note", note?: BulletNote) => void;
  onComposerChange: (next: Composer | null) => void;
  onSave: (item: ReviewItem, bullet: ReviewBullet) => void;
  onDeleteNote: (noteId: number) => void;
  onDraft: (next: Draft | null) => void;
  onSubmitDraft: () => void;
  onAddItem: (section: "experience" | "projects", parentKey: string | null) => void;
  onAddBullet: (itemKey: string) => void;
  onDeleteItem: (item: ReviewItem) => void;
  onDeleteBullet: (item: ReviewItem, bullet: ReviewBullet) => void;
}) {
  const children = onlyWithNotes
    ? (item.children ?? []).filter(itemHasNotes)
    : (item.children ?? []);
  const bullets = item.bullets.filter((b) => {
    if (onlyWithNotes) return b.notes.length > 0;
    if (b.is_whole) return b.notes.length > 0;
    return true;
  });
  const count = noteCount(item);
  const renaming = draft?.kind === "rename" && draft.itemKey === item.item_key;

  return (
    <div>
      <div className="mb-2 flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          {renaming && draft?.kind === "rename" ? (
            <div className="space-y-2">
              <input
                value={draft.title}
                onChange={(e) => onDraft({ ...draft, title: e.target.value })}
                className="w-full rounded-lg border border-zinc-200 px-3 py-1.5 text-sm outline-none focus:border-sky-400 dark:border-zinc-700 dark:bg-zinc-950"
                placeholder="名称"
              />
              {item.section_type === "experience" && (
                <input
                  value={draft.subtitle}
                  onChange={(e) => onDraft({ ...draft, subtitle: e.target.value })}
                  className="w-full rounded-lg border border-zinc-200 px-3 py-1.5 text-sm outline-none focus:border-sky-400 dark:border-zinc-700 dark:bg-zinc-950"
                  placeholder="岗位 · 时间"
                />
              )}
              <div className="flex gap-2">
                <button type="button" className={btnCls("primary", "sm")} disabled={saving} onClick={onSubmitDraft}>
                  保存
                </button>
                <button type="button" className={btnCls("ghost", "sm")} onClick={() => onDraft(null)}>
                  取消
                </button>
              </div>
            </div>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <h3
                  className={`${
                    nested ? "text-[15px]" : "text-base"
                  } font-semibold text-zinc-900 dark:text-zinc-50`}
                >
                  {item.title}
                </h3>
                {count > 0 && <Badge tone="emerald">{count} 条复习</Badge>}
              </div>
              {item.subtitle ? (
                <p className="mt-0.5 text-sm text-zinc-500">{item.subtitle}</p>
              ) : null}
            </>
          )}
        </div>
        {editable && !renaming && (
          <div className="flex shrink-0 gap-1">
            <button
              type="button"
              className={btnCls("ghost", "sm")}
              onClick={() =>
                onDraft({
                  kind: "rename",
                  itemKey: item.item_key,
                  title: item.title,
                  subtitle: item.subtitle,
                })
              }
            >
              编辑
            </button>
            <button type="button" className={btnCls("ghost", "sm")} onClick={() => onDeleteItem(item)}>
              删除
            </button>
          </div>
        )}
      </div>
      <ul className="divide-y divide-zinc-100 dark:divide-zinc-800">
        {bullets.map((bullet) => {
          const key = composerKey(item.item_key, bullet.bullet_key);
          const open = openKeys.has(key);
          const editing =
            draft?.kind === "edit-bullet" &&
            draft.itemKey === item.item_key &&
            draft.bulletKey === bullet.bullet_key;
          const activeComposer =
            composer &&
            composer.itemKey === item.item_key &&
            composer.bulletKey === bullet.bullet_key
              ? composer
              : null;
          return (
            <li key={bullet.bullet_key}>
              {editing && draft?.kind === "edit-bullet" ? (
                <div className="space-y-2 py-3">
                  <textarea
                    value={draft.text}
                    onChange={(e) => onDraft({ ...draft, text: e.target.value })}
                    rows={4}
                    className="w-full resize-y rounded-lg border border-zinc-200 px-3 py-2 text-sm outline-none focus:border-sky-400 dark:border-zinc-700 dark:bg-zinc-950"
                  />
                  <div className="flex gap-2">
                    <button type="button" className={btnCls("primary", "sm")} disabled={saving} onClick={onSubmitDraft}>
                      保存
                    </button>
                    <button type="button" className={btnCls("ghost", "sm")} onClick={() => onDraft(null)}>
                      取消
                    </button>
                  </div>
                </div>
              ) : (
                <div className="flex items-start gap-1">
                  <button
                    type="button"
                    onClick={() => onToggle(item.item_key, bullet.bullet_key)}
                    className="flex min-w-0 flex-1 items-start gap-3 py-3 text-left transition hover:bg-sky-50/50 dark:hover:bg-zinc-800/60"
                  >
                    <span
                      className={`mt-1 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-md border text-[10px] text-zinc-400 transition ${
                        open ? "rotate-90 border-sky-300 text-sky-600" : "border-zinc-200"
                      }`}
                    >
                      ▸
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="text-sm leading-6 text-zinc-800 dark:text-zinc-100">
                        {bullet.text}
                      </span>
                      {bullet.notes.length > 0 && (
                        <span className="ml-2 text-xs text-zinc-400">{bullet.notes.length} 条</span>
                      )}
                    </span>
                  </button>
                  {editable && !bullet.is_whole && (
                    <div className="mt-2 flex shrink-0 gap-1">
                      <button
                        type="button"
                        className={btnCls("ghost", "sm")}
                        onClick={() =>
                          onDraft({
                            kind: "edit-bullet",
                            itemKey: item.item_key,
                            bulletKey: bullet.bullet_key,
                            text: bullet.text,
                          })
                        }
                      >
                        编辑
                      </button>
                      <button
                        type="button"
                        className={btnCls("ghost", "sm")}
                        onClick={() => onDeleteBullet(item, bullet)}
                      >
                        删除
                      </button>
                    </div>
                  )}
                </div>
              )}
              {open && (
                <div className="space-y-3 bg-slate-50/80 px-5 pb-4 pt-1 dark:bg-zinc-950/40">
                  {bullet.notes.map((note) =>
                    activeComposer?.editingId === note.id ? null : (
                      <NoteCard
                        key={note.id}
                        note={note}
                        onEdit={() => onComposer(item, bullet, note.kind === "note" ? "note" : "qa", note)}
                        onDelete={() => onDeleteNote(note.id)}
                      />
                    )
                  )}
                  {activeComposer ? (
                    <ComposerForm
                      composer={activeComposer}
                      saving={saving}
                      onChange={onComposerChange}
                      onSave={() => onSave(item, bullet)}
                      onCancel={() => onComposerChange(null)}
                    />
                  ) : (
                    <div className="flex flex-wrap gap-2 pt-1">
                      <button
                        type="button"
                        className={btnCls("secondary", "sm")}
                        onClick={() => onComposer(item, bullet, "qa")}
                      >
                        + QA
                      </button>
                      <button
                        type="button"
                        className={btnCls("ghost", "sm")}
                        onClick={() => onComposer(item, bullet, "note")}
                      >
                        + 注释
                      </button>
                    </div>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ul>
      {editable && (
        <button
          type="button"
          className={`${btnCls("ghost", "sm")} mt-1`}
          disabled={saving}
          onClick={() => onAddBullet(item.item_key)}
        >
          + 添加 bullet
        </button>
      )}
      {item.orphan_notes.length > 0 && (
        <div className="mt-3 border-t border-amber-100 bg-amber-50/70 px-4 py-3 dark:border-amber-900/40 dark:bg-amber-950/20">
          <p className="text-xs text-amber-800 dark:text-amber-300">
            原句已变更，笔记仍归属本段经历
          </p>
          <div className="mt-2 space-y-2">
            {item.orphan_notes.map((note) =>
              composer?.editingId === note.id ? (
                <ComposerForm
                  key={note.id}
                  composer={composer}
                  saving={saving}
                  onChange={onComposerChange}
                  onSave={() => onSave(item, item.bullets[0])}
                  onCancel={() => onComposerChange(null)}
                />
              ) : (
                <NoteCard
                  key={note.id}
                  note={note}
                  onEdit={() =>
                    onComposer(item, item.bullets[0], note.kind === "note" ? "note" : "qa", note)
                  }
                  onDelete={() => onDeleteNote(note.id)}
                />
              )
            )}
          </div>
        </div>
      )}
      {children.length > 0 && (
        <div className="mt-5 space-y-6 border-l border-zinc-200 pl-4 dark:border-zinc-700">
          {children.map((child) => (
            <ItemBlock
              key={child.item_key}
              item={child}
              nested
              openKeys={openKeys}
              composer={composer}
              saving={saving}
              draft={draft}
              onlyWithNotes={onlyWithNotes}
              editable={editable}
              onToggle={onToggle}
              onComposer={onComposer}
              onComposerChange={onComposerChange}
              onSave={onSave}
              onDeleteNote={onDeleteNote}
              onDraft={onDraft}
              onSubmitDraft={onSubmitDraft}
              onAddItem={onAddItem}
              onAddBullet={onAddBullet}
              onDeleteItem={onDeleteItem}
              onDeleteBullet={onDeleteBullet}
            />
          ))}
        </div>
      )}
      {editable && item.section_type === "experience" && (
        <button
          type="button"
          className={`${btnCls("ghost", "sm")} mt-3`}
          disabled={saving}
          onClick={() => onAddItem("experience", item.item_key)}
        >
          + 在此实习下添加项目
        </button>
      )}
    </div>
  );
}

function NoteCard({
  note,
  onEdit,
  onDelete,
}: {
  note: BulletNote;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const isQa = note.kind === "qa";
  return (
    <div
      className={`rounded-xl border px-3.5 py-3 ${
        isQa
          ? "border-sky-100 bg-white dark:border-sky-900/40 dark:bg-zinc-900"
          : "border-amber-100 bg-amber-50/80 dark:border-amber-900/40 dark:bg-amber-950/30"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <Badge tone={isQa ? "sky" : "amber"}>{isQa ? "QA" : "注释"}</Badge>
        <div className="flex gap-1">
          <button type="button" className={btnCls("ghost", "sm")} onClick={onEdit}>
            编辑
          </button>
          <button type="button" className={btnCls("ghost", "sm")} onClick={onDelete}>
            删除
          </button>
        </div>
      </div>
      {isQa ? (
        <div className="mt-2 space-y-1.5 text-sm">
          <p className="font-medium text-zinc-800 dark:text-zinc-100">Q. {note.question}</p>
          {note.answer ? (
            <p className="whitespace-pre-wrap text-zinc-600 dark:text-zinc-300">A. {note.answer}</p>
          ) : (
            <p className="text-xs text-zinc-400">暂无回答</p>
          )}
        </div>
      ) : (
        <p className="mt-2 whitespace-pre-wrap text-sm text-zinc-700 dark:text-zinc-200">{note.body}</p>
      )}
    </div>
  );
}

function ComposerForm({
  composer,
  saving,
  onChange,
  onSave,
  onCancel,
}: {
  composer: Composer;
  saving: boolean;
  onChange: (next: Composer) => void;
  onSave: () => void;
  onCancel: () => void;
}) {
  const isQa = composer.kind === "qa";
  const canSave = isQa ? composer.question.trim().length > 0 : composer.body.trim().length > 0;
  return (
    <div className="rounded-xl border border-sky-200 bg-white p-3.5 dark:border-sky-900/50 dark:bg-zinc-900">
      <p className="text-xs font-medium text-sky-700">
        {composer.editingId ? "编辑" : "新增"}
        {isQa ? "QA" : "注释"}
      </p>
      {isQa ? (
        <div className="mt-2 space-y-2">
          <textarea
            value={composer.question}
            onChange={(e) => onChange({ ...composer, question: e.target.value })}
            placeholder="问题"
            rows={2}
            className="w-full resize-y rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm outline-none focus:border-sky-400 focus:ring-2 focus:ring-sky-500/20 dark:border-zinc-700 dark:bg-zinc-950"
          />
          <textarea
            value={composer.answer}
            onChange={(e) => onChange({ ...composer, answer: e.target.value })}
            placeholder="回答"
            rows={3}
            className="w-full resize-y rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm outline-none focus:border-sky-400 focus:ring-2 focus:ring-sky-500/20 dark:border-zinc-700 dark:bg-zinc-950"
          />
        </div>
      ) : (
        <textarea
          value={composer.body}
          onChange={(e) => onChange({ ...composer, body: e.target.value })}
          placeholder="注释"
          rows={3}
          className="mt-2 w-full resize-y rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm outline-none focus:border-sky-400 focus:ring-2 focus:ring-sky-500/20 dark:border-zinc-700 dark:bg-zinc-950"
        />
      )}
      <div className="mt-3 flex justify-end gap-2">
        <button type="button" className={btnCls("ghost", "sm")} onClick={onCancel}>
          取消
        </button>
        <button
          type="button"
          className={btnCls("primary", "sm")}
          disabled={saving || !canSave}
          onClick={onSave}
        >
          {saving ? "保存中…" : "保存"}
        </button>
      </div>
    </div>
  );
}
