import type { LocalePreference } from "./preferences";

const catalogs = {
  en: {
    automation: "Automation",
    automationNav: "Automation",
    automationDetail:
      "Agents, workflows, schedules, and compatibility guardian retain one backend workflow contract across every client.",
    automationEyebrow: "Agents · Workflows · Schedules",
    approvals: "Approvals",
    attention: "Attention",
    boundaryDescription:
      "These modules are excluded from initial route JavaScript and load only after selection.",
    boundaryEmpty: "Choose an inspector to prove the lazy boundary.",
    boundaryEyebrow: "On-demand code",
    boundaryTitle: "Inspector boundaries",
    close: "Close",
    connected: "Connected",
    connection: "Local connection ready",
    dark: "Dark",
    diff: "Diff",
    diffDescription: "Diff rendering loads only when opened.",
    editor: "Editor",
    editorDescription: "Editor rendering loads only when opened.",
    evaluation: "Evaluation",
    evaluationDetail:
      "Arena, evals, baselines, and scorecards remain server-authoritative while the new route boundary is proven.",
    evaluationEyebrow: "Compare pinned evidence",
    integrations: "Integrations",
    integrationsDetail:
      "Harnesses, routes, models, MCP, and doctor readiness will expose content-free diagnostics through bounded projections.",
    integrationsEyebrow: "Effective connectivity",
    language: "Language",
    lazyBoundary: "Lazy inspector boundary",
    light: "Light",
    loadingInspector: "Loading inspector…",
    legacy: "Open legacy cockpit",
    markdown: "Markdown",
    markdownDescription: "Markdown rendering loads only when opened.",
    migrationNote:
      "Shell boundary active · authoritative data remains in FastAPI · no surface migration yet",
    noItems: "No retained items in this shell-only projection.",
    presentationOnly: "Presentation preferences only",
    project: "Harness workspace",
    rawEvidence: "Raw evidence",
    rawEvidenceDescription: "Raw evidence code loads only when opened.",
    runs: "Runs",
    runsDetail:
      "Durable ownership, trace, artifacts, review, replay, and promotion stay on their current APIs until the vertical migration gate.",
    runsEyebrow: "Evidence → Review → Reuse",
    settings: "Settings",
    settingsDescription:
      "Credentials, policy grants, raw paths, and authoritative runtime state never live here.",
    shellNotice:
      "The packaged Cockpit V2 shell is ready. Surface migration remains intentionally disabled until later roadmap slices.",
    system: "System",
    terminal: "Terminal",
    terminalDescription: "Terminal rendering loads only when opened.",
    theme: "Theme",
    workbench: "Workbench",
    workbenchDetail:
      "Sessions, execution, and retained evidence will migrate here after bounded read models and stream contracts exist.",
    workbenchEyebrow: "Work → Run → Evidence",
  },
  ru: {
    automation: "Автоматизация",
    automationNav: "Автомат.",
    automationDetail:
      "Агенты, workflows, расписания и compatibility guardian сохраняют единый backend-контракт workflow для всех клиентов.",
    automationEyebrow: "Агенты · Workflows · Расписания",
    approvals: "Согласования",
    attention: "Внимание",
    boundaryDescription:
      "Эти модули исключены из начального JavaScript маршрута и загружаются только после выбора.",
    boundaryEmpty: "Выберите inspector, чтобы проверить ленивую границу.",
    boundaryEyebrow: "Код по запросу",
    boundaryTitle: "Границы inspector-модулей",
    close: "Закрыть",
    connected: "Подключено",
    connection: "Локальное соединение готово",
    dark: "Тёмная",
    diff: "Diff",
    diffDescription: "Отображение diff загружается только при открытии.",
    editor: "Редактор",
    editorDescription: "Редактор загружается только при открытии.",
    evaluation: "Оценка",
    evaluationDetail:
      "Arena, evals, baselines и scorecards остаются под управлением сервера, пока проверяется новая граница маршрута.",
    evaluationEyebrow: "Сравнение закреплённых evidence",
    integrations: "Интеграции",
    integrationsDetail:
      "Harnesses, маршруты, модели, MCP и doctor readiness будут показывать content-free диагностику через ограниченные projections.",
    integrationsEyebrow: "Эффективные подключения",
    language: "Язык",
    lazyBoundary: "Ленивая граница inspector",
    light: "Светлая",
    loadingInspector: "Загрузка inspector…",
    legacy: "Открыть legacy cockpit",
    markdown: "Markdown",
    markdownDescription: "Отображение Markdown загружается только при открытии.",
    migrationNote:
      "Граница shell активна · FastAPI сохраняет полномочия · миграция поверхностей ещё не началась",
    noItems: "В этой shell-only projection нет сохранённых элементов.",
    presentationOnly: "Только настройки представления",
    project: "Рабочая область Harness",
    rawEvidence: "Исходные evidence",
    rawEvidenceDescription: "Код исходных evidence загружается только при открытии.",
    runs: "Запуски",
    runsDetail:
      "Durable ownership, trace, artifacts, review, replay и promotion остаются на текущих API до vertical migration gate.",
    runsEyebrow: "Evidence → Review → Reuse",
    settings: "Настройки",
    settingsDescription:
      "Credentials, policy grants, исходные пути и authoritative runtime state здесь не хранятся.",
    shellNotice:
      "Пакетный shell Cockpit V2 готов. Миграция поверхностей намеренно отключена до следующих slices roadmap.",
    system: "Системная",
    terminal: "Терминал",
    terminalDescription: "Терминал загружается только при открытии.",
    theme: "Тема",
    workbench: "Рабочая область",
    workbenchDetail:
      "Сессии, выполнение и сохранённые evidence будут перенесены сюда после появления ограниченных read models и stream contracts.",
    workbenchEyebrow: "Работа → Запуск → Evidence",
  },
} as const;

export type MessageKey = keyof (typeof catalogs)["en"];

export function message(locale: LocalePreference, key: MessageKey): string {
  return catalogs[locale][key];
}
