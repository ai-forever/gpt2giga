"""Small locale catalog for the built-in terminal client."""

from __future__ import annotations

import os


CATALOGS: dict[str, dict[str, str]] = {
    "en": {
        "app.subtitle": "Provider-neutral terminal workbench",
        "button.help": "Help",
        "button.answer": "Answer",
        "button.approve": "Approve",
        "button.cancel_run": "Cancel run",
        "button.deny": "Deny",
        "button.fork": "Fork",
        "button.files": "Files",
        "button.evidence": "Evidence",
        "button.terminal": "Terminal",
        "button.provider": "Provider",
        "button.web": "Web",
        "button.new_project": "Project",
        "button.new_session": "New session",
        "button.refresh": "Refresh",
        "button.send": "Send",
        "composer.placeholder": "Message or steer the active run",
        "detail.empty": "Select a session or create a new one.",
        "dialog.cancel": "Cancel",
        "dialog.confirm": "Open",
        "dialog.close": "Close",
        "dialog.file_query": "@file search (empty lists safe project files)",
        "dialog.input_answer": "Answer provider question",
        "dialog.project_path": "Project path",
        "dialog.session_title": "Session title (optional)",
        "help.body": (
            "Tab / Shift+Tab: move focus\n"
            "Arrow keys: navigate lists\n"
            "Ctrl+P: command palette\n"
            "Enter: resume selected session\n"
            "P: choose project path\n"
            "N: create session\n"
            "A: attach a safe project file\n"
            "E: inspect diff and evidence\n"
            "T: return to a contained native terminal\n"
            "O / W: preview provider / Web handoff\n"
            "R: refresh\n"
            "?: help\n"
            "Q: quit"
        ),
        "help.title": "Keyboard help",
        "label.harness": "Harness",
        "label.model": "Model",
        "label.provider": "Provider",
        "label.readiness": "Readiness",
        "label.transport": "Transport",
        "pane.projects": "Projects",
        "pane.readiness": "Session readiness",
        "pane.sessions": "Sessions",
        "provider.pending": "pending execution snapshot",
        "attachments.empty": "No files selected for the next turn.",
        "attachments.selected": "Files",
        "evidence.empty": "No retained run is selected. Start or resume a run first.",
        "evidence.no_diff": "No diff was retained for this run.",
        "evidence.title": "Run diff and evidence",
        "evidence.truncated": "Diff preview is truncated; authoritative evidence remains retained.",
        "files.attach": "Attach",
        "files.attached": "Project file attached to the next turn",
        "files.empty": "No safe matching files. Hidden safe files may appear; ignored and denied paths do not.",
        "files.no_session": "Select or create a session before choosing a file.",
        "files.policy": "Hidden files are shown only when safe and not ignored. Git-ignored and denied paths are excluded. Symlinks must resolve inside the project and are canonicalized.",
        "files.title": "Project files",
        "handoff.no_session": "Select or create a session before previewing a handoff.",
        "handoff.title": "External handoff preview",
        "session.created": "Session created",
        "status.attach": "Attached client",
        "status.error": "Error",
        "status.in_process": "In-process client",
        "status.loading": "Loading authoritative state…",
        "status.loading_evidence": "Loading authoritative run evidence…",
        "status.loading_files": "Searching safe project files…",
        "status.loading_handoff": "Resolving exact handoff target…",
        "status.ready": "Ready",
        "status.resnapshot": "Authoritative resnapshot",
        "status.running": "Run active",
        "status.native_terminal": "Native terminal contained in TUI",
        "status.finished": "Run finished",
        "status.disconnected": "Disconnected; retrying",
        "status.reconnected": "Reconnected to authoritative state",
        "terminal.fullscreen_blocked": "Unsupported provider screen controls were blocked. Use the reviewed provider handoff instead; no raw terminal fallback was opened.",
        "terminal.no_process": "No retained native-terminal process is available for this run.",
        "terminal.return": "Return",
        "terminal.stop": "Stop",
        "terminal.title": "Contained native terminal",
        "timeline.empty": "No run events yet.",
        "timeline.approval": "APPROVAL",
        "timeline.error": "ERROR",
        "timeline.question": "QUESTION",
        "timeline.reasoning": "REASONING",
        "timeline.status": "STATUS",
        "timeline.tool": "TOOL",
        "timeline.warning": "WARNING",
    },
    "ru": {
        "app.subtitle": "Провайдер-независимая рабочая среда",
        "button.help": "Помощь",
        "button.answer": "Ответить",
        "button.approve": "Разрешить",
        "button.cancel_run": "Отменить запуск",
        "button.deny": "Отклонить",
        "button.fork": "Ответвить",
        "button.files": "Файлы",
        "button.evidence": "Данные",
        "button.terminal": "Терминал",
        "button.provider": "Провайдер",
        "button.web": "Web",
        "button.new_project": "Проект",
        "button.new_session": "Новая сессия",
        "button.refresh": "Обновить",
        "button.send": "Отправить",
        "composer.placeholder": "Сообщение или уточнение активного запуска",
        "detail.empty": "Выберите сессию или создайте новую.",
        "dialog.cancel": "Отмена",
        "dialog.confirm": "Открыть",
        "dialog.close": "Закрыть",
        "dialog.file_query": "Поиск @file (пустой запрос покажет безопасные файлы)",
        "dialog.input_answer": "Ответ на вопрос провайдера",
        "dialog.project_path": "Путь к проекту",
        "dialog.session_title": "Название сессии (необязательно)",
        "help.body": (
            "Tab / Shift+Tab: сменить фокус\n"
            "Стрелки: навигация по спискам\n"
            "Ctrl+P: палитра команд\n"
            "Enter: продолжить выбранную сессию\n"
            "P: выбрать путь проекта\n"
            "N: создать сессию\n"
            "A: прикрепить безопасный файл проекта\n"
            "E: открыть diff и данные запуска\n"
            "T: вернуться во встроенный native-терминал\n"
            "O / W: проверить переход к провайдеру / Web\n"
            "R: обновить\n"
            "?: помощь\n"
            "Q: выйти"
        ),
        "help.title": "Клавиатурная помощь",
        "label.harness": "Harness",
        "label.model": "Модель",
        "label.provider": "Провайдер",
        "label.readiness": "Готовность",
        "label.transport": "Транспорт",
        "pane.projects": "Проекты",
        "pane.readiness": "Готовность сессии",
        "pane.sessions": "Сессии",
        "provider.pending": "ожидает снимка выполнения",
        "attachments.empty": "Файлы для следующего сообщения не выбраны.",
        "attachments.selected": "Файлы",
        "evidence.empty": "Запуск не выбран. Сначала запустите или продолжите сессию.",
        "evidence.no_diff": "Для этого запуска diff не сохранён.",
        "evidence.title": "Diff и данные запуска",
        "evidence.truncated": "Предпросмотр diff сокращён; авторитетные данные сохранены.",
        "files.attach": "Прикрепить",
        "files.attached": "Файл проекта прикреплён к следующему сообщению",
        "files.empty": "Безопасных совпадений нет. Скрытые безопасные файлы могут отображаться; ignored и запрещённые пути исключены.",
        "files.no_session": "Выберите или создайте сессию перед выбором файла.",
        "files.policy": "Скрытые файлы видны только если безопасны и не ignored. Git-ignored и запрещённые пути исключены. Симлинки должны разрешаться внутри проекта и канонизируются.",
        "files.title": "Файлы проекта",
        "handoff.no_session": "Выберите или создайте сессию перед переходом.",
        "handoff.title": "Предпросмотр внешнего перехода",
        "session.created": "Сессия создана",
        "status.attach": "Подключённый клиент",
        "status.error": "Ошибка",
        "status.in_process": "Локальный клиент",
        "status.loading": "Загрузка авторитетного состояния…",
        "status.loading_evidence": "Загрузка авторитетных данных запуска…",
        "status.loading_files": "Поиск безопасных файлов проекта…",
        "status.loading_handoff": "Определение точной цели перехода…",
        "status.ready": "Готово",
        "status.resnapshot": "Обновление авторитетного снимка",
        "status.running": "Запуск активен",
        "status.native_terminal": "Native-терминал изолирован внутри TUI",
        "status.finished": "Запуск завершён",
        "status.disconnected": "Связь потеряна; повторная попытка",
        "status.reconnected": "Связь с авторитетным состоянием восстановлена",
        "terminal.fullscreen_blocked": "Неподдерживаемые управляющие последовательности экрана заблокированы. Используйте проверенный переход к провайдеру; raw-terminal fallback не открывался.",
        "terminal.no_process": "Для этого запуска нет сохранённого native-terminal процесса.",
        "terminal.return": "Вернуться",
        "terminal.stop": "Остановить",
        "terminal.title": "Изолированный native-терминал",
        "timeline.empty": "Событий запуска пока нет.",
        "timeline.approval": "РАЗРЕШЕНИЕ",
        "timeline.error": "ОШИБКА",
        "timeline.question": "ВОПРОС",
        "timeline.reasoning": "РАССУЖДЕНИЕ",
        "timeline.status": "СТАТУС",
        "timeline.tool": "ИНСТРУМЕНТ",
        "timeline.warning": "ПРЕДУПРЕЖДЕНИЕ",
    },
}


def resolve_locale(value: str | None = None) -> str:
    """Resolve the supported presentation locale with English fallback."""
    candidate = value or os.getenv("LC_ALL") or os.getenv("LANG") or "en"
    normalized = candidate.strip().lower().replace("-", "_").split("_", 1)[0]
    return normalized if normalized in CATALOGS else "en"


def translator(locale: str | None = None):
    """Return one stable catalog lookup callable."""
    selected = CATALOGS[resolve_locale(locale)]
    fallback = CATALOGS["en"]

    def translate(key: str) -> str:
        return selected.get(key, fallback.get(key, key))

    return translate
