# Release checklist for the 1.0 line

Этот checklist фиксирует реальный release gate для текущей ветки `1.0.0rc3` / `1.0.0`.
Он опирается на текущие workflow-ы и packaging assumptions репозитория, а не на абстрактный "идеальный" процесс.

## Когда использовать

Пройдите этот список перед:

- публикацией release tag-а `v*`
- подготовкой финального `1.0.0` или очередного `1.0.0rc*`
- merge-ем PR, который меняет release-facing version surface, packaging, canonical docs или admin asset pipeline

## 1. Version and release surface

- [ ] `pyproject.toml` и `packages/gpt2giga-ui/pyproject.toml` указывают один и тот же release version.
- [ ] Верхние записи в `CHANGELOG.md` и `CHANGELOG_en.md` соответствуют этому version.
- [ ] Если готовится GitHub release, tag имеет вид `v<version>` и совпадает с version в обоих package manifests.
- [ ] `README.md`, `docs/README.md`, `docs/operator-guide.md`, `docs/api-compatibility.md` и `docs/upgrade-0.x-to-1.0.md` не ссылаются на устаревшую release line.

## 2. Canonical docs and migration story

- [ ] `docs/README.md` остаётся canonical entry point для operator-facing docs.
- [ ] Internal working notes по-прежнему живут под `docs/internal/` и не surfaced как обычная документация.
- [ ] Upgrade path из `0.1.x` в `1.0` остаётся актуальным и соответствует текущему runtime/config layout.
- [ ] Support boundary `Stable` / `Partial` / `Unsupported` в `docs/api-compatibility.md` всё ещё честно описывает shipped surface.

## 3. Python quality and packaging

- [ ] `uv sync --all-extras --dev`
- [ ] `uv run ruff check .`
- [ ] `uv run ruff format --check .`
- [ ] `uv build`
- [ ] `(cd packages/gpt2giga-ui && uv build --out-dir ../../dist)`
- [ ] `uv run pytest tests/ --cov=. --cov-report=term --cov-fail-under=80`

Это повторяет основной CI release gate из `.github/workflows/ci.yaml` и build expectations publish workflow-а `.github/workflows/publish-pypi.yml`.

## 4. Admin UI and committed asset sync

- [ ] `npm ci`
- [ ] `npm run test:admin`
- [ ] `npm run build:admin`
- [ ] `npm run verify:admin-assets`
- [ ] Если менялись файлы под `gpt2giga/frontend/admin/`, соответствующие compiled assets под `packages/gpt2giga-ui/src/gpt2giga_ui/static/admin/` закоммичены.

Это обязательно, потому что текущие Docker/PyPI release paths используют committed repository state как source of truth для admin UI.

## 5. Docker and runtime smoke

- [ ] `docker build --build-arg PYTHON_VERSION=3.13 -t gpt2giga:release-smoke .`
- [ ] Контейнер поднимается хотя бы в `DEV`-режиме и `GET /health` отвечает успешно.
- [ ] Если менялись `Dockerfile`, `deploy/compose/**` или runtime boot path, сверено, что `.github/workflows/docker-smoke.yaml` всё ещё отражает реальный smoke path.

Минимальный локальный smoke можно повторить так:

```bash
docker run -d --rm \
  --name gpt2giga-release-smoke \
  -p 18090:8090 \
  -e GPT2GIGA_MODE=DEV \
  -e GPT2GIGA_HOST=0.0.0.0 \
  gpt2giga:release-smoke

curl --fail --silent http://127.0.0.1:18090/health
docker stop gpt2giga-release-smoke
```

## 6. Publish path sanity

- [ ] GitHub release publication is expected to trigger `.github/workflows/publish-pypi.yml`.
- [ ] Docker publish expectations still match `.github/workflows/publish-ghcr.yml`: Python matrix `3.10`-`3.14`, with version and `latest` tags emitted from the `3.13` job.
- [ ] Никакой release-facing PR не оставил drift между docs, package versions, compiled admin assets и publish workflows.

## 7. Final human pass

- [ ] Проверен `.github/PULL_REQUEST_TEMPLATE.md` checklist для релизного PR.
- [ ] Release notes / draft summary не обещают больше, чем реально поддерживает текущий surface.
- [ ] Нет незакоммиченных generated files, локальных секретов или временных release edits.

Если один из пунктов не проходит, релизную линию лучше задержать на исправление, чем выпускать ещё один неясный RC.
