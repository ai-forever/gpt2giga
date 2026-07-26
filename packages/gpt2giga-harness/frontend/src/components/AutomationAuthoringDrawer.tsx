import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  defaultDefinition,
  duplicateDefinition,
  parseScheduleContent,
  scheduleContentFromForm,
  scheduleFormFromContent,
  sourceFromDetail,
  type AutomationAuthoringRequest,
  type DeletePreview,
  type ScheduleFormDefinition,
} from "../automation-authoring";
import {
  deleteCockpit,
  fetchCockpit,
  mutateCockpit,
  putCockpit,
  withQuery,
} from "../api";
import { message } from "../messages";
import { usePreferences } from "../preferences-context";
import { remainingRequestKeys } from "../remaining-request-graph";

type UnknownRecord = Record<string, unknown>;

export function AutomationAuthoringDrawer({
  request,
  onClose,
}: {
  request: AutomationAuthoringRequest;
  onClose: () => void;
}) {
  const { preferences } = usePreferences();
  const locale = preferences.locale;
  const detail = useQuery({
    queryKey: ["cockpit", "automation-authoring", request.section, request.id],
    queryFn: ({ signal }) =>
      fetchCockpit<unknown>(detailPath(request.section, request.id ?? ""), signal),
    enabled: request.mode !== "create" && Boolean(request.id),
    staleTime: 0,
  });

  let seed = defaultDefinition(request.section);
  let sourceHash: string | null = null;
  if (request.mode !== "create" && detail.data !== undefined) {
    const loaded = sourceFromDetail(request.section, detail.data);
    const prepared =
      request.mode === "duplicate"
        ? duplicateDefinition(request.section, loaded)
        : loaded;
    seed = { id: prepared.id, content: prepared.content };
    sourceHash = prepared.sourceHash;
  }

  return (
    <div className="automation-authoring-backdrop" onMouseDown={onClose} role="presentation">
      <section
        aria-label={message(locale, "authoringLifecycle")}
        aria-modal="true"
        className="automation-authoring-drawer"
        onMouseDown={(event) => event.stopPropagation()}
        role="dialog"
      >
        {detail.isPending && request.mode !== "create" ? (
          <div className="authoring-loading">{message(locale, "loading")}</div>
        ) : detail.isError ? (
          <AuthoringError error={detail.error} onClose={onClose} />
        ) : request.mode === "delete" && request.id ? (
          <DeleteDefinition
            id={request.id}
            onClose={onClose}
            section={request.section}
          />
        ) : (
          <DefinitionEditor
            key={`${request.mode}:${request.section}:${seed.id}:${sourceHash ?? "new"}`}
            mode={request.mode}
            onClose={onClose}
            section={request.section}
            seed={seed}
            sourceHash={sourceHash}
          />
        )}
      </section>
    </div>
  );
}

function DefinitionEditor({
  mode,
  onClose,
  section,
  seed,
  sourceHash,
}: {
  mode: AutomationAuthoringRequest["mode"];
  onClose: () => void;
  section: AutomationAuthoringRequest["section"];
  seed: { id: string; content: string };
  sourceHash: string | null;
}) {
  const { preferences } = usePreferences();
  const locale = preferences.locale;
  const queryClient = useQueryClient();
  const [id, setId] = useState(seed.id);
  const [content, setContent] = useState(seed.content);
  const [scheduleForm, setScheduleForm] = useState<ScheduleFormDefinition | null>(
    () => section === "schedules" ? scheduleFormFromContent(seed.content) : null,
  );
  const preview = useMutation({
    mutationFn: () => previewDefinition(section, id.trim(), content, sourceHash),
  });
  const apply = useMutation({
    mutationFn: () =>
      applyDefinition(
        section,
        id.trim(),
        content,
        preview.data,
        mode === "edit",
        sourceHash,
      ),
    onSuccess: async (response) => {
      await queryClient.invalidateQueries({
        queryKey: remainingRequestKeys.automation(),
      });
      if (record(response).approval_required === true) {
        globalThis.dispatchEvent(
          new CustomEvent("cockpit:open-inbox", { detail: "approvals" }),
        );
      } else {
        onClose();
      }
    },
  });
  const resetPreview = () => {
    if (preview.data || preview.isError) preview.reset();
    if (apply.data || apply.isError) apply.reset();
  };
  const updateSchedule = (next: ScheduleFormDefinition, nextId = id) => {
    setScheduleForm(next);
    setContent(scheduleContentFromForm(nextId, next));
    resetPreview();
  };

  return (
    <>
      <header className="automation-authoring-header">
        <div>
          <span className="section-kicker">{message(locale, "authoringLifecycle")}</span>
          <h2>
            {message(
              locale,
              mode === "edit"
                ? "authoringEdit"
                : mode === "duplicate"
                  ? "authoringDuplicate"
                  : "authoringCreate",
            )}
          </h2>
        </div>
        <button aria-label={message(locale, "cancelAuthoring")} onClick={onClose} type="button">×</button>
      </header>
      <p className="authoring-guidance">
        {message(locale, "authoringValidationHint")}{" "}
        {message(locale, "authoringStaleHint")}
      </p>
      <label className="field-control">
        {message(locale, "authoringId")}
        <input
          disabled={mode === "edit"}
          onChange={(event) => {
            const nextId = event.target.value;
            setId(nextId);
            if (scheduleForm) {
              setContent(scheduleContentFromForm(nextId, scheduleForm));
            }
            resetPreview();
          }}
          value={id}
        />
      </label>
      {section === "schedules" && scheduleForm ? (
        <>
          <ScheduleFormEditor
            form={scheduleForm}
            locale={locale}
            onChange={updateSchedule}
          />
          <details className="schedule-advanced-source">
            <summary>{locale === "ru" ? "Advanced · JSON" : "Advanced · JSON"}</summary>
            <label className="field-control authoring-source-field">
              {message(locale, "authoringSource")}
              <textarea
                onChange={(event) => {
                  const nextContent = event.target.value;
                  setContent(nextContent);
                  try {
                    setScheduleForm(scheduleFormFromContent(nextContent));
                  } catch {
                    // Keep invalid JSON editable; Preview reports the exact error.
                  }
                  resetPreview();
                }}
                spellCheck={false}
                value={content}
              />
            </label>
          </details>
        </>
      ) : (
        <label className="field-control authoring-source-field">
          {message(locale, "authoringSource")}
          <textarea
            onChange={(event) => {
              setContent(event.target.value);
              resetPreview();
            }}
            spellCheck={false}
            value={content}
          />
        </label>
      )}
      <div className="authoring-actions">
        <button disabled={preview.isPending || !id.trim() || !content.trim()} onClick={() => preview.mutate()} type="button">
          {message(locale, "authoringPreview")}
        </button>
        <button className="primary-button" disabled={!preview.data || apply.isPending} onClick={() => apply.mutate()} type="button">
          {message(locale, "authoringApply")}
        </button>
      </div>
      {preview.isError ? <p className="mutation-error" role="alert">{preview.error.message}</p> : null}
      {preview.data ? <AuthoringPreview response={preview.data} /> : null}
      {apply.isError ? <p className="mutation-error" role="alert">{apply.error.message}</p> : null}
      {record(apply.data).approval_required === true ? (
        <p className="mutation-success" role="status">{message(locale, "approvalRequired")}</p>
      ) : null}
    </>
  );
}

function ScheduleFormEditor({
  form,
  locale,
  onChange,
}: {
  form: ScheduleFormDefinition;
  locale: "en" | "ru";
  onChange: (next: ScheduleFormDefinition) => void;
}) {
  const update = <Key extends keyof ScheduleFormDefinition>(
    key: Key,
    value: ScheduleFormDefinition[Key],
  ) => onChange({ ...form, [key]: value });
  return (
    <div className="schedule-form-editor">
      <div className="schedule-form-intro">
        <strong>{locale === "ru" ? "Что запускать и когда" : "What should run, and when"}</strong>
        <span>
          {locale === "ru"
            ? "Как в Codex Scheduled: выберите готовую частоту, время и изолированную цель. RRULE остаётся в Advanced."
            : "Like Codex Scheduled: choose a familiar cadence, time, and isolated target. RRULE stays under Advanced."}
        </span>
      </div>
      <label className="field-control">
        {locale === "ru" ? "Название" : "Title"}
        <input onChange={(event) => update("title", event.target.value)} value={form.title} />
      </label>
      <div className="schedule-field-row">
        <label className="field-control">
          {locale === "ru" ? "Тип цели" : "Target type"}
          <select
            onChange={(event) => update("targetKind", event.target.value as ScheduleFormDefinition["targetKind"])}
            value={form.targetKind}
          >
            <option value="workflow">Workflow</option>
            <option value="agent">Agent</option>
            <option value="eval">Eval</option>
          </select>
        </label>
        <label className="field-control">
          {locale === "ru" ? "ID цели" : "Target id"}
          <input onChange={(event) => update("targetId", event.target.value)} value={form.targetId} />
        </label>
      </div>
      <fieldset className="schedule-cadence-options">
        <legend>{locale === "ru" ? "Повтор" : "Repeat"}</legend>
        {(["once", "daily", "weekdays", "weekly", "custom"] as const).map((preset) => (
          <button
            aria-pressed={form.cadencePreset === preset}
            className={form.cadencePreset === preset ? "selected" : ""}
            key={preset}
            onClick={() => update("cadencePreset", preset)}
            type="button"
          >
            {cadenceLabel(locale, preset)}
          </button>
        ))}
      </fieldset>
      <div className="schedule-field-row">
        <label className="field-control">
          {locale === "ru" ? "Первый запуск" : "First run"}
          <input
            onChange={(event) => update("startAt", event.target.value)}
            type="datetime-local"
            value={form.startAt}
          />
        </label>
        <label className="field-control">
          {locale === "ru" ? "Часовой пояс IANA" : "IANA timezone"}
          <input onChange={(event) => update("timezone", event.target.value)} value={form.timezone} />
        </label>
      </div>
      {form.cadencePreset === "weekly" ? (
        <label className="field-control">
          {locale === "ru" ? "День недели" : "Weekday"}
          <select onChange={(event) => update("weekday", event.target.value)} value={form.weekday}>
            {[
              ["MO", "Monday"], ["TU", "Tuesday"], ["WE", "Wednesday"],
              ["TH", "Thursday"], ["FR", "Friday"], ["SA", "Saturday"], ["SU", "Sunday"],
            ].map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
      ) : null}
      {form.cadencePreset === "custom" ? (
        <label className="field-control">
          RRULE
          <input onChange={(event) => update("customRrule", event.target.value)} value={form.customRrule} />
        </label>
      ) : null}
      <label className="field-control">
        {locale === "ru" ? "Задача" : "Prompt"}
        <textarea
          className="schedule-prompt"
          onChange={(event) => update("prompt", event.target.value)}
          value={form.prompt}
        />
      </label>
      <label className="check-control">
        <input
          checked={form.desktopNotifications}
          onChange={(event) => update("desktopNotifications", event.target.checked)}
          type="checkbox"
        />
        {locale === "ru" ? "Показывать desktop notification" : "Show a desktop notification"}
      </label>
      <p className="schedule-worktree-note">
        {locale === "ru"
          ? "Каждый запуск использует отдельный worktree. Сначала Preview, затем Test schedule, и только после этого Enable."
          : "Every run uses a separate worktree. Preview first, then Test schedule, and only then Enable."}
      </p>
    </div>
  );
}

function cadenceLabel(
  locale: "en" | "ru",
  cadence: ScheduleFormDefinition["cadencePreset"],
) {
  const labels = {
    en: { once: "Once", daily: "Daily", weekdays: "Weekdays", weekly: "Weekly", custom: "Custom" },
    ru: { once: "Один раз", daily: "Каждый день", weekdays: "По будням", weekly: "Раз в неделю", custom: "Другое" },
  };
  return labels[locale][cadence];
}

function DeleteDefinition({
  id,
  onClose,
  section,
}: {
  id: string;
  onClose: () => void;
  section: AutomationAuthoringRequest["section"];
}) {
  const { preferences } = usePreferences();
  const locale = preferences.locale;
  const queryClient = useQueryClient();
  const [confirmId, setConfirmId] = useState("");
  const preview = useMutation({
    mutationFn: () =>
      mutateCockpit<DeletePreview>(
        `/api/${section}/${encodeURIComponent(id)}/delete-preview`,
        {},
      ),
  });
  const apply = useMutation({
    mutationFn: async () => {
      if (!preview.data) throw new Error("Preview deletion first.");
      if (section === "schedules") {
        return deleteCockpit<unknown>(
          withQuery(`/api/schedules/${encodeURIComponent(id)}`, {
            expected_hash: preview.data.source_hash,
            confirm_id: confirmId,
          }),
        );
      }
      return mutateCockpit<unknown>(
        `/api/${section}/${encodeURIComponent(id)}/delete`,
        {
          expected_hash: preview.data.source_hash,
          confirm_id: confirmId,
        },
      );
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: remainingRequestKeys.automation(),
      });
      onClose();
    },
  });

  return (
    <>
      <header className="automation-authoring-header">
        <div>
          <span className="section-kicker">{message(locale, "authoringLifecycle")}</span>
          <h2>{message(locale, "authoringDelete")}</h2>
        </div>
        <button aria-label={message(locale, "cancelAuthoring")} onClick={onClose} type="button">×</button>
      </header>
      <p className="authoring-guidance">{message(locale, "authoringDeleteHint")}</p>
      <code className="authoring-target-id">{id}</code>
      <button disabled={preview.isPending} onClick={() => preview.mutate()} type="button">
        {message(locale, "authoringPreview")}
      </button>
      {preview.data ? (
        <>
          <section className="authoring-preview">
            <strong>{message(locale, "dependentDefinitions")}: {preview.data.dependents.length}</strong>
            {preview.data.dependents.map((item) => (
              <span key={`${item.kind}:${item.id}`}>{item.kind} · {item.id} · {item.status}</span>
            ))}
          </section>
          <label className="field-control">
            {message(locale, "confirmExactId")}
            <input onChange={(event) => setConfirmId(event.target.value)} value={confirmId} />
          </label>
          <button className="danger-button" disabled={confirmId !== id || apply.isPending} onClick={() => apply.mutate()} type="button">
            {message(locale, "authoringDelete")}
          </button>
        </>
      ) : null}
      {preview.isError ? <p className="mutation-error" role="alert">{preview.error.message}</p> : null}
      {apply.isError ? <p className="mutation-error" role="alert">{apply.error.message}</p> : null}
    </>
  );
}

function AuthoringPreview({ response }: { response: unknown }) {
  const { preferences } = usePreferences();
  const root = record(response);
  const diff = typeof root.redacted_diff === "string" ? root.redacted_diff : null;
  const occurrences = Array.isArray(root.occurrences) ? root.occurrences.length : null;
  return (
    <section className="authoring-preview">
      <strong>{message(preferences.locale, "authoringPreviewReady")}</strong>
      {diff ? <pre>{diff}</pre> : null}
      {occurrences !== null ? <span>{occurrences} upcoming occurrences</span> : null}
    </section>
  );
}

function AuthoringError({ error, onClose }: { error: Error; onClose: () => void }) {
  const { preferences } = usePreferences();
  return (
    <div className="error-state" role="alert">
      <strong>{message(preferences.locale, "boundedDataUnavailable")}</strong>
      <span>{error.message}</span>
      <button onClick={onClose} type="button">{message(preferences.locale, "cancelAuthoring")}</button>
    </div>
  );
}

function detailPath(section: AutomationAuthoringRequest["section"], id: string): string {
  return `/api/${section}/${encodeURIComponent(id)}`;
}

async function previewDefinition(
  section: AutomationAuthoringRequest["section"],
  id: string,
  content: string,
  sourceHash: string | null,
): Promise<unknown> {
  if (section === "schedules") {
    return mutateCockpit("/api/schedules/preview", parseScheduleContent(content));
  }
  const suffix = section === "agents" ? "draft" : "draft";
  return mutateCockpit(`/api/${section}/${encodeURIComponent(id)}/${suffix}`, {
    content,
    ...(sourceHash ? { expected_hash: sourceHash } : {}),
  });
}

async function applyDefinition(
  section: AutomationAuthoringRequest["section"],
  id: string,
  content: string,
  preview: unknown,
  editing: boolean,
  sourceHash: string | null,
): Promise<unknown> {
  const previewRecord = record(preview);
  if (section === "agents") {
    return mutateCockpit(`/api/agents/${encodeURIComponent(id)}/apply`, {
      content,
      expected_hash: previewRecord.source_hash,
    });
  }
  if (section === "workflows") {
    return mutateCockpit(`/api/workflows/${encodeURIComponent(id)}/apply`, {
      content,
      expected_hash: previewRecord.source_hash,
    });
  }
  const payload = parseScheduleContent(content);
  return editing
    ? putCockpit(`/api/schedules/${encodeURIComponent(id)}`, {
        ...payload,
        expected_hash: sourceHash ?? undefined,
      })
    : mutateCockpit("/api/schedules", payload);
}

function record(value: unknown): UnknownRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as UnknownRecord)
    : {};
}
