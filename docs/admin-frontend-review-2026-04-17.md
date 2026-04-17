# Review: admin frontend (`/admin`)

Дата: 2026-04-17

Область:
- `gpt2giga/frontend/admin/`
- `packages/gpt2giga-ui/src/gpt2giga_ui/templates/console.html`
- `packages/gpt2giga-ui/src/gpt2giga_ui/static/admin/console.css`

Формат:
- что нравится;
- что не нравится;
- что выглядит как баг или риск;
- что выглядит как сильная фича или удачное решение;
- что спорно, но может быть осознанным tradeoff.

Ограничение этого обзора:
- это code/UI audit по исходникам и структуре;
- это не pixel-perfect визуальная проверка в живом браузере;
- MCP-ресурсов для готовых frontend-артефактов в этой сессии не было.

Правило выполнения задач из этого review:
- прогресс и сделанные срезы нужно записывать в `docs/admin-frontend-review-2026-04-17-worklog.md`;
- законченные и проверенные срезы нужно фиксировать отдельными commit-ами, а не оставлять только в рабочем дереве.

## Короткий вывод

Текущий admin frontend сильный по архитектуре, сценариям оператора и общей визуальной теме.
Это уже не "набор страниц", а довольно цельная operator console.

Главные плюсы:
- сильная информационная архитектура;
- хорошие page-to-page handoff;
- дисциплинированная frontend-структура для vanilla TypeScript;
- заметно лучше среднего базовая accessibility;
- продуманная URL-state модель в diagnostic surfaces.

Главные минусы:
- есть несколько конкретных safety-проблем из-за string-based rendering;
- copy-density местами всё ещё выше нужного;
- несколько UX-решений не добиты на mobile/accessibility;
- нет защиты от потери несохранённых изменений между внутренними переходами.

## Что нравится

### 1. Сильная информационная архитектура

Навигация разбита не по техническим сущностям, а по operator workflow:
- `Start`
- `Configure`
- `Observe`
- `Diagnose`

Это видно в:
- `packages/gpt2giga-ui/src/gpt2giga_ui/templates/console.html`
- `gpt2giga/frontend/admin/routes.ts`

Это правильное решение. Консоль помогает понять "что делать дальше", а не просто "куда можно кликнуть".

### 2. Хороший операторский storytelling

Во многих экранах чувствуется одна и та же идея:
- сначала summary-first поверхность;
- затем narrowed scope;
- затем handoff в более глубокую страницу;
- raw details открываются только когда уже есть контекст.

Особенно хорошо это сделано в:
- `render-overview.ts`
- `render-setup.ts`
- `pages/traffic/view.ts`
- `pages/logs/view.ts`
- `pages/files-batches/view.ts`

Это не просто "copy". Это уже UX-логика продукта.

### 3. Чистая структура frontend-кода

Для vanilla TypeScript код разложен очень дисциплинированно:
- `render-*`
- `view`
- `bindings`
- `serializers`
- `state`

Сильные зоны:
- `pages/playground/*`
- `pages/logs/*`
- `pages/traffic/*`
- `pages/files-batches/*`

Это повышает:
- читаемость;
- локальность изменений;
- предсказуемость поведения;
- шанс, что UI можно дальше развивать без полного переписывания.

### 4. Хорошая базовая accessibility-подготовка

Есть важные базовые вещи, которые часто забывают:
- skip-link;
- нормальная семантическая структура `nav / main / header`;
- `aria-live` для alerts;
- `aria-current` в навигации;
- `focus-visible`;
- фокус на заголовок после навигации.

Ключевые места:
- `console.html`
- `console.css`
- `app.ts`

Это ещё не "идеально доступный интерфейс", но фундамент уже хороший.

### 5. Визуальное направление удачное

Плюсы визуально:
- тёплая палитра вместо типового синевато-серого CRUD;
- хорошо работает sticky rail;
- glass/panel treatment не мешает читаемости;
- страница выглядит как продукт, а не как сырая dev-tool поверхность.

Ключевой файл:
- `packages/gpt2giga-ui/src/gpt2giga_ui/static/admin/console.css`

### 6. URL-state и shareable diagnostics

Сильный плюс у diagnostic screens:
- `traffic`;
- `logs`;
- `files-batches`.

Там есть реальный URL-state:
- фильтры;
- pinning;
- handoff между экранами;
- history updates.

Это важно для operator tooling. Ссылкой можно поделиться, вернуться назад, восстановить контекст.

## Что не нравится

### 1. Copy-density всё ещё местами выше оптимума

Во фронтенде очень много "операторской" copy.
Часть её полезна, но часть уже конкурирует с самими данными.

Сильнее всего это видно в:
- `render-overview.ts`
- `render-setup.ts`
- `render-providers.ts`
- `pages/traffic/view.ts`
- `pages/logs/view.ts`

Проблема не в качестве текста.
Проблема в том, что на ряде экранов интерфейс объясняет себя дольше, чем оператору реально нужно.

### 2. Слишком много равнозначных panel/surface-блоков

Визуально много сущностей имеют почти одинаковый вес:
- panel;
- surface;
- workflow-card;
- form-section;
- details-disclosure.

Из-за этого на длинных страницах первый экран иногда не очень жёстко отвечает на вопрос:
"что здесь главное прямо сейчас?"

Это не ломает UI, но снижает visual hierarchy.

### 3. Некоторые input-паттерны недожаты

Местами поля сделаны минимально рабочими, но не оптимальными:
- URL-поля не используют `type="url"`;
- ключевые поля почти не используют `autocomplete`;
- нет заметной mobile/input ergonomics настройки.

Примеры:
- `console.html`
- `control-plane-sections.ts`
- `render-keys.ts`

### 4. Disabled-state местами объясняется только через `title`

В `Files/Batches` и рядом логика понятна по коду, но пользователю не всегда понятна по интерфейсу.
Если кнопка disabled и причина только в `title`, то:
- на touch это почти не помогает;
- на клавиатуре тоже;
- для screen-reader это слабый паттерн.

Дополнительно CSS сейчас делает любой disabled button визуально похожим на "ожидающий":
- `button:disabled { cursor: wait; }`

Это неверный сигнал для permanently unavailable action.

### 5. Слишком большой упор на string-rendering

Сейчас UI рендерится через HTML-строки и `innerHTML`.
Это даёт скорость и простоту, но создаёт системный долг:
- выше риск XSS;
- выше риск пропустить одно неэкранированное значение;
- сложнее делать безопасные incremental UI changes.

Это не обязательно повод всё переписывать.
Но это уже architectural tradeoff, который виден не только в коде, но и в классе возникающих рисков.

## Что выглядит как баг или риск

### P1. Неэкранированная ошибка в аварийном рендере страницы

Файл:
- `gpt2giga/frontend/admin/app.ts`

Место:
- блок error fallback с `<pre class="code-block">${toErrorMessage(error)}</pre>`

Проблема:
- `toErrorMessage(error)` вставляется в `innerHTML` без `escapeHtml`;
- если сообщение ошибки содержит HTML, админка его отрисует.

Это уже не вкусовщина, а реальная XSS-поверхность.

### P1. Неэкранированное имя файла в `alt` изображения

Файл:
- `gpt2giga/frontend/admin/pages/files-batches/bindings.ts`

Место:
- image preview через `elements.mediaNode.innerHTML = ...`

Проблема:
- `preview.filename` попадает в `alt` без экранирования;
- имя файла может быть пользовательским.

Тоже реальный XSS-риск.

### P2. Нет защиты от потери несохранённых изменений

Файлы:
- `gpt2giga/frontend/admin/app.ts`
- `gpt2giga/frontend/admin/pages/control-plane-form-bindings.ts`

Проблема:
- формы умеют считать diff и pending state;
- SPA navigation активно перехватывает внутренние ссылки;
- но guard на unsaved changes нет.

В результате можно:
- набрать изменения;
- уйти в другой экран;
- потерять правки без предупреждения.

Для settings-heavy operator UI это заметный UX-баг.

### P2. Нет ветки для `prefers-reduced-motion`

Файл:
- `packages/gpt2giga-ui/src/gpt2giga_ui/static/admin/console.css`

Проблема:
- интерфейс использует transitions/transforms;
- но reduced-motion fallback отсутствует.

Это accessibility gap.

### P2. Disabled cursor вводит в заблуждение

Файл:
- `packages/gpt2giga-ui/src/gpt2giga_ui/static/admin/console.css`

Место:
- `.button:disabled { cursor: wait; }`

Проблема:
- disabled action часто означает "недоступно по состоянию";
- `wait` означает "сейчас идёт операция".

Это маленький, но системный UX-изъян.

### P2. Security-sensitive значение показывается прямо в alert после ротации global key

Файл:
- `gpt2giga/frontend/admin/pages/render-setup.ts`

Место:
- обработчик `setup-create-global-key`

Проблема:
- после rotation новый global key выводится в alert целиком;
- это может быть намеренной логикой "show once";
- но повышает риск shoulder-surfing, скриншотов и случайной утечки на демонстрациях.

Это не обязательный bug, но это точно security-sensitive UX decision.

### P3. Часть дат показывается как сырое значение, а не через единый formatter

Пример:
- `render-setup.ts` для claim pills

Проблема:
- в одних местах используется `formatTimestamp`;
- в других значениях даты/времени идут как `String(...)`.

Это мелочь, но создаёт непоследовательность UI.

## Что выглядит как сильная фича

### 1. Summary-first diagnostics

Очень удачное решение:
- `Traffic` как primary summary surface;
- `Logs` как request-scoped raw surface;
- `System` и `Providers` как posture/diagnostics surface;
- `Files/Batches` как отдельный workbench.

Это хорошая продуктовая сегментация.

### 2. Setup flow реально помогает, а не просто дублирует settings

`Setup` не выглядит как лишняя обёртка над `Settings`.
Он реально:
- сужает задачу;
- показывает следующий recommended step;
- держит bootstrap flow под контролем.

Это особенно удачно в:
- `render-setup.ts`
- `control-plane-form-bindings.ts`
- `control-plane-status.ts`

### 3. Pending diff и runtime-impact copy

Это одна из самых сильных частей интерфейса.
UI не просто даёт форму, а объясняет:
- что меняется;
- что restart-sensitive;
- что не будет применено live;
- что только staged.

Для operator console это очень правильное направление.

### 4. Shared templates и reusable UI primitives

Файлы:
- `templates.ts`
- `forms.ts`

Плюс:
- есть набор общих примитивов;
- они достаточно простые;
- через них поддерживается общая визуальная и контентная модель.

Это помогает не расползтись интерфейсу в разные стороны.

### 5. Deep-linking между surfaces

Почти везде есть осмысленный handoff:
- из overview в setup/settings/logs/playground;
- из traffic в logs;
- из files/batches в logs/traffic;
- из providers в scoped traffic/logs.

Это ощущается как продуманная operator system, а не как набор isolated pages.

## Что спорно, но может быть осознанным tradeoff

### 1. Очень явная операторская copy

С одной стороны:
- это перегружает интерфейс.

С другой:
- это делает продукт самодокументируемым;
- для редких операторов или first-run experience это реально помогает.

Вероятно, оптимум не в полном удалении copy, а в её уплотнении.

### 2. String-based rendering вместо framework

С одной стороны:
- выше safety-риск;
- сложнее масштабировать.

С другой:
- текущая админка грузится просто;
- структура уже дисциплинированная;
- нет framework overhead;
- для optional UI package это прагматично.

То есть проблема не в том, что это vanilla TS.
Проблема в том, что вокруг string rendering теперь нужен более жёсткий safety discipline.

### 3. Показ нового global key один раз

С точки зрения usability:
- это полезно;
- оператор реально видит значение сразу.

С точки зрения security UX:
- это спорно.

Это не "явно неверно", но требует чёткого продуктового решения, а не случайного поведения.

## Дополнение: живой проход через `chrome_devtools`

После основного code review был сделан отдельный live-pass по локальному UI:
- `http://localhost:8090/admin`
- `Overview`
- `Setup`
- `Playground`
- `Settings`
- `Keys`
- `Traffic`
- `Logs`
- `Providers`
- `Files & Batches`
- `System`

Что подтвердилось в живом UI дополнительно:

### 1. Readiness/copy реально расходятся с фактическим поведением

Это главный новый finding из live-pass.

Наблюдение:
- `Overview`, `Setup`, `Playground`, `Settings`, `System` показывают, что GigaChat credentials missing;
- UI повторяет, что playground calls will fail;
- но реальный запрос из `Playground` успешно проходит и возвращает `200 OK`.

Следствие:
- либо readiness-эвристика неверна;
- либо copy не соответствует реальному runtime;
- либо разные источники состояния в UI противоречат друг другу.

Это уже точно не теоретический риск, а подтверждённая продуктовая несостыковка.

Важное уточнение по observed runtime:
- при `DISABLE_PERSIST=True` control-plane persistence отключена;
- в таком режиме persisted settings могут отсутствовать полностью;
- но effective runtime всё равно может иметь рабочие GigaChat credentials из environment / `.env`;
- значит UI обязан различать:
  - `persisted control-plane credentials missing`;
  - `effective runtime credentials available`;
  - `effective runtime credentials unavailable`.

То есть проблема не в том, что при `DISABLE_PERSIST=True` playground успешно отвечает.
Проблема в том, что UI сейчас, похоже, смешивает отсутствие persisted state с отсутствием runtime auth readiness и из-за этого сообщает оператору более жёсткую неисправность, чем есть на самом деле.

### 2. `Traffic` и `Logs` реально загрязняются browser/admin шумом

Это видно в живых списках recent requests/errors:
- `GET /`
- `GET /favicon.ico`
- `GET /robots.txt`

Проблема:
- summary-first surfaces частично заняты не операторским proxy traffic, а браузерным и shell-шумом;
- из-за этого request review и recent panels теряют signal-to-noise ratio;
- первый экран `Traffic` не всегда показывает то, что оператор реально хочет видеть в day-2 диагностике.

Это особенно заметно на:
- `Traffic summary`
- `Logs`
- `System > Route coverage`

### 3. Route-family/coverage view тоже частично унаследовал этот шум

В live UI `System` и `Providers` относят `/` к OpenAI-совместимому route surface.

Это не обязательно технически неверно на уровне route table, но для operator mental model это спорно:
- `/` воспринимается как UI/root redirect;
- в диагностике provider surfaces он шумит рядом с реальными compatibility endpoints.

То есть тут проблема не в mounted route как таковом, а в operator-facing классификации.

### 4. Playground request preview даёт смешанный сигнал по auth

В live `Playground` одновременно видно:
- текст: `Gateway key empty. Request will be sent without proxy auth headers.`
- и в preview строку: `AUTH = Authorization: Bearer`

Это не ломает запрос, но создаёт двусмысленность в preview.
Пользователь получает два разных сигнала о том, будет ли auth header отправлен.

Это скорее UX/data-presentation bug, чем функциональная ошибка.

### 5. `Logs` по умолчанию стартует с тяжёлого startup-tail, а не с самого полезного request context

В живой `Logs` surface:
- rendered tail сильно заполнен startup/config dump;
- `Tail context` при этом пишет, что request ids не извлечены;
- полезный request context уже есть ниже в `Recent requests`, но первый большой экран занят длинным boot log.

Это не значит, что `Logs` плохой.
Это значит, что default first impression у этой страницы менее полезен, чем мог бы быть.

### 6. Lighthouse snapshot подтверждает сильный baseline

Live audit через browser tooling показал:
- Accessibility: `100`
- Best Practices: `100`
- SEO: `75`

Это подтверждает вывод из code review:
- accessibility foundation действительно сильная;
- интерфейс не выглядит как хаотичный набор div-ов.

При этом SEO проседает как минимум из-за отсутствия `meta description`.

## Что я бы делал дальше по приоритету

### Сначала

1. Закрыть XSS-поверхности:
   - error fallback;
   - image preview `alt`;
   - быстро пройтись ещё раз по всем местам с `innerHTML`.

2. Добавить unsaved changes guard:
   - хотя бы для settings/setup форм;
   - отдельно для SPA navigation и `beforeunload`.

3. Исправить disabled-state UX:
   - не использовать `cursor: wait` для всех disabled buttons;
   - вынести причину недоступности в видимый текст или inline note.

4. Починить inconsistent readiness/copy:
   - если playground реально работает, UI не должен утверждать, что credentials missing и calls will fail;
   - при `DISABLE_PERSIST=True` отдельно показывать `persisted state unavailable` и `effective runtime ready from env`;
   - привести `Overview`, `Setup`, `Settings`, `System`, `Playground` к одному источнику правды.

5. Отфильтровать operator surfaces от browser noise:
   - убрать или спрятать `GET /`, `GET /favicon.ico`, `GET /robots.txt` из primary request summaries;
   - отдельно решить, должны ли такие route-ы попадать в provider-facing coverage.

### Потом

1. Добавить `prefers-reduced-motion`.
2. Нормализовать input semantics:
   - `type="url"` там, где это URL;
   - `autocomplete` для ключевых полей;
   - где уместно, `inputmode`.
3. Подсушить copy на overview/setup/providers/traffic.
4. Пересобрать default-first-screen для `Logs`, чтобы startup tail не оттеснял request context.

### Позже

1. Ужесточить policy для HTML-string rendering:
   - либо централизованный safe helper;
   - либо постепенное сокращение ручных HTML-вставок в самых рискованных местах.
2. Ещё сильнее расставить visual hierarchy на длинных страницах.

## Итоговая оценка

Если коротко:

- как продуктовая operator console: хорошо;
- как frontend architecture для vanilla TS: хорошо;
- как visual/system design: хорошо;
- как accessibility baseline: выше среднего;
- как safety discipline вокруг `innerHTML`: пока недостаточно строго;
- как UX для длинных day-2 экранов: хороший фундамент, но ещё есть место для уплотнения и приоритизации.

Главная мысль:

Проблема этого фронтенда сейчас не в том, что он "плохой".
Проблема в том, что он уже стал достаточно серьёзным интерфейсом, и теперь ему нужен следующий уровень строгости:
- по безопасности;
- по состояниям форм;
- по сокращению текста;
- по точности UX-мелочей.
