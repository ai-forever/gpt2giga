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
        "button.new_project": "Project",
        "button.new_session": "New session",
        "button.refresh": "Refresh",
        "button.send": "Send",
        "composer.placeholder": "Message or steer the active run",
        "detail.empty": "Select a session or create a new one.",
        "dialog.cancel": "Cancel",
        "dialog.confirm": "Open",
        "dialog.input_answer": "Answer provider question",
        "dialog.project_path": "Project path",
        "dialog.session_title": "Session title (optional)",
        "help.body": (
            "Tab / Shift+Tab: move focus\n"
            "Arrow keys: navigate lists\n"
            "Enter: resume selected session\n"
            "P: choose project path\n"
            "N: create session\n"
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
        "session.created": "Session created",
        "status.attach": "Attached client",
        "status.error": "Error",
        "status.in_process": "In-process client",
        "status.loading": "Loading authoritative state…",
        "status.ready": "Ready",
        "status.resnapshot": "Authoritative resnapshot",
        "status.running": "Run active",
        "status.finished": "Run finished",
        "timeline.empty": "No run events yet.",
    },
    "ru": {
        "app.subtitle": "Провайдер-независимая рабочая среда",
        "button.help": "Помощь",
        "button.answer": "Ответить",
        "button.approve": "Разрешить",
        "button.cancel_run": "Отменить запуск",
        "button.deny": "Отклонить",
        "button.fork": "Ответвить",
        "button.new_project": "Проект",
        "button.new_session": "Новая сессия",
        "button.refresh": "Обновить",
        "button.send": "Отправить",
        "composer.placeholder": "Сообщение или уточнение активного запуска",
        "detail.empty": "Выберите сессию или создайте новую.",
        "dialog.cancel": "Отмена",
        "dialog.confirm": "Открыть",
        "dialog.input_answer": "Ответ на вопрос провайдера",
        "dialog.project_path": "Путь к проекту",
        "dialog.session_title": "Название сессии (необязательно)",
        "help.body": (
            "Tab / Shift+Tab: сменить фокус\n"
            "Стрелки: навигация по спискам\n"
            "Enter: продолжить выбранную сессию\n"
            "P: выбрать путь проекта\n"
            "N: создать сессию\n"
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
        "session.created": "Сессия создана",
        "status.attach": "Подключённый клиент",
        "status.error": "Ошибка",
        "status.in_process": "Локальный клиент",
        "status.loading": "Загрузка авторитетного состояния…",
        "status.ready": "Готово",
        "status.resnapshot": "Обновление авторитетного снимка",
        "status.running": "Запуск активен",
        "status.finished": "Запуск завершён",
        "timeline.empty": "Событий запуска пока нет.",
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
