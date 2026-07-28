# ADR: архитектура сборки frontend assets

Статус: принято для slice G8-03 roadmap GigaLoom 2026-07-28.

Статус реализации: реализовано в G8-04 2026-07-28. Compiled bundles теперь
ignored; source и tests закрепляют deterministic producer, Python-only
fail-closed consumer, commit-bound передачу между CI/release jobs, sealed sdist,
SBOM/license evidence и rollback contract.

## Контекст

Cockpit написан на React и TypeScript в
`packages/gpt2giga-harness/frontend`. Закреплённый npm-граф создаёт
content-addressed и integrity-checked дерево assets внутри Python package.
Установленный Harness wheel обслуживает его без Node.js и network access.

Сейчас compiled tree хранится в Git. Harness sdist намеренно не содержит
frontend source и npm toolchain, но сохраняет compiled assets. Поэтому из него
можно offline собрать wheel без Node.js, однако нельзя заново получить assets
из authored frontend или доказать соответствие его revision.

G8-04 должен удалить compiled JS, CSS, source maps и generated declarations из
Git без потери следующих свойств:

- clean source создаёт wheel и sdist;
- wheel из sdist остаётся Node-free и обслуживает Cockpit offline;
- Gateway и Harness можно собирать независимо;
- отсутствующие, устаревшие или подменённые assets останавливают build, а не
  создают wheel со сломанным UI;
- producer toolchain, licenses, SBOM, output hashes и release provenance
  проверяемы и воспроизводимы.

Offline build здесь означает, что все locked Python/npm inputs либо уже
созданный verified asset artifact доступны локально. Это не обещание
восстановить npm dependencies на пустой машине без cache или переданных
artifacts.

## Сравнение вариантов

| Критерий | PEP 517 Node build hook | Отдельный versioned asset package | CI-injected verified assets |
| --- | --- | --- | --- |
| Clean-clone build | Неявно запускает npm внутри Python build | Требует два release artifacts | Явный producer step, затем обычный Python build |
| Offline Python build | Требует Node и npm cache | Требует локальный asset package | Требует только verified asset tree |
| Node availability | Нужен producer каждого wheel и sdist | Нужен только producer asset package | Нужен только frontend producer job |
| Editable install | Скрытые Node side effects при install | Version skew Python и assets | Явная local frontend build в ignored staging tree |
| Wheel из sdist | Требует frontend source, Node и npm inputs | Требует ещё один точный package | Использует sealed verified tree внутри sdist |
| Cache и reproducibility | PEP 517 cache скрывает второй package-manager graph | Хороши внутри artifact, но нужно синхронизировать две версии | Asset digest служит cache key и Python input |
| Platform support | Каждый Python build platform требует Node toolchain | Runtime portable, release ordering сложнее | Producer работает на pinned platform, wheel остаётся pure Python |
| SBOM и licenses | Python/npm evidence смешаны в opaque build | Evidence привязана к asset package | Producer публикует отдельную npm SBOM/license evidence |
| Release recovery | Повторить смешанный Python/Node build | Сначала восстановить и выпустить точную asset version | Пересобрать или восстановить commit-bound artifact, затем Python |
| Контракт репозитория | Два package, но PEP 517 запускает Node | Третья независимо versioned distribution | Два workspace member и один Harness runtime artifact |

### PEP 517 Node build hook

Hatch build hooks умеют добавлять ignored generated artifacts и force-include
файлы в build target. Они подходят для validation и inclusion, но запуск
`npm ci` и Vite внутри hook сделает Node и npm-граф неявными требованиями
каждого isolated Python source build. PEP 517 build isolation не описывает и
не устанавливает такой non-Python graph. Wheel из sdist также потребует Node и
frontend source, а editable install получит скрытые side effects.

Вариант отклонён. G8-04 может добавить Python-only Hatch hook для проверки и
включения уже созданного дерева; это consumer guard, а не Node build hook.

### Отдельный versioned asset package

Выделенный asset wheel или archive даёт frontend собственную release identity,
но GigaLoom не требует независимого runtime rollout browser shell. Появятся
третья distribution, exact-version coupling, release ordering, дополнительный
offline-install input и новый recovery path для asset/Python skew. Текущий
two-member workspace и один Harness artifact проще и уже дают нужную runtime
границу.

Вариант отклонён. К нему можно вернуться только при самостоятельном release
cadence Cockpit или нескольких Python consumers.

### CI-injected verified assets

Frontend producer и Python consumer остаются разными build stages. Producer
использует pinned Node/npm graph и создаёт одно полное дерево Cockpit. CI
передаёт его как commit-bound, content-addressed build artifact в Python build,
который проверяет и включает дерево в Harness wheel и sdist. Asset artifact —
build input, а не отдельная опубликованная runtime dependency.

Этот вариант выбран.

## Решение

G8-04 реализует следующий контракт.

1. Authored TypeScript, configuration, npm lockfile, canonical brand source и
   deterministic producer scripts остаются tracked. Compiled output создаётся
   в ignored staging tree по существующему Python resource path, чтобы
   installed и editable loaders использовали один путь.
2. Одна документированная producer command начинает с чистого staging tree,
   выполняет pinned frontend build и создаёт существующий per-file integrity
   manifest плюс content-free provenance. Provenance связывает Git revision,
   frontend input digest, lockfile digest, canonical brand digest, версии
   Node/npm, output-tree digest и SBOM/license evidence.
3. CI и release workflow запускают producer в отдельном Node job и передают
   точное дерево и provenance в Python artifact job. Передача проверяется по
   hash и привязана к той же source revision; mutable “latest” assets не
   загружаются.
4. Python-only Hatch consumer проверяет manifest, размеры и hashes всех файлов,
   полный allowlisted tree, provenance, source revision при наличии authored
   source, а также отсутствие symlinks, path escapes и неожиданных файлов.
   Missing или stale input завершается ошибкой с точной local recovery command.
5. Verified tree включается в direct wheel и sdist. Sdist остаётся sealed
   Python source artifact: содержит verified Cockpit tree и consumer metadata,
   но не frontend toolchain. Wheel из sdist не требует Node или network.
6. Editable development использует тот же ignored staging path. Явная frontend
   producer command атомарно обновляет его; verifier отвергает
   source/provenance mismatch, поэтому старый local output не может затенить
   новый authored source.
7. Gateway build остаётся полностью независимым. Harness build имеет два явных
   режима: produce-and-package из source checkout либо consume ранее
   проверенного дерева из того же CI/release run.
8. Release evidence совместно хранит asset digest, npm SBOM/license report,
   hashes Python wheel/sdist и provenance attestation. Rollback берёт source
   прошлого release и либо детерминированно пересобирает, либо восстанавливает
   его commit-bound verified asset artifact до Python build.

Consumer никогда не запускает npm, не обращается к registry, не принимает
unsigned или mutable asset location и не создаёт wheel без Cockpit.

## Evidence spike

Локальный spike G8-03 использовал Git archive принятого revision G8-02 и удалял
compiled assets только внутри временной копии.

- `npm ci --offline --ignore-scripts` восстановил 301 package из local cache, а
  production producer заново создал 53 packaged asset files.
- Обычный frontend gate прошёл 37 test files и 137 tests. Две production build
  дали одинаковый asset-tree digest:
  `997003971b3db91353df7d11410f4250d468a596ee6ee1388ee342a3a5a6ec9b`.
- Direct injected Harness wheel и Node-free wheel из его sdist были побитово
  одинаковы:
  `4d6773a1edef8a65f4de02edb75d8fc522aed474f9213895340f64d1f96f1af0`.
- Sdist сохранил verified asset manifest и не включил frontend toolchain.
- Build того же temporary source с пустым asset directory сейчас успешно
  создаёт неполный wheel. Это доказывает, что fail-closed Python consumer
  обязателен до удаления tracked output.

Локальный spike использовал Node.js 22.12, тогда как repository contract и CI
требуют 22.13 или новее; npm сообщил о mismatch. Это окружение не принимается
как release evidence. G8-04 должен выполнить reproducibility, platform,
SBOM/license и release recovery gates на pinned toolchain.

## Последствия

Python package build остаётся deterministic, offline-capable и Node-free при
получении verified tree. Frontend production становится явным supply-chain
stage с проверяемой evidence, а не implicit side effect или tracked source.

Цена решения — новый staging/verification contract и CI artifact handoff.
G8-04 должен реализовать и проверить их до удаления любого tracked compiled
file. До этого текущий bundle остаётся rollback и packaging source.

## Ссылки

- [Hatch build-hook interface](https://github.com/pypa/hatch/blob/master/docs/plugins/build-hook/reference.md)
- [Hatch generated-artifact configuration](https://github.com/pypa/hatch/blob/master/docs/config/build.md)
