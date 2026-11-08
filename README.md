# Календарь звонков


[![hexlet-check](https://github.com/Kamazoh1/ai-for-developers-project-387/actions/workflows/hexlet-check.yml/badge.svg)](https://github.com/Kamazoh1/ai-for-developers-project-387/actions)

Разработайте совместно с ИИ сервис для бронирования календаря

Учебный проект Хекслета: https://ru.hexlet.io/programs/ai-for-developers
Как это должно работать: https://files.hexlet.app/a/2ipc5m

Тестовый стенд на Render: https://call-calendar-xbuh.onrender.com (бесплатный план: после простоя первый запрос идёт около минуты, данные сбрасываются при каждом редеплое и перезапуске)

## Стек

- Бекенд: Python 3.13, FastAPI, uv, pytest, ruff, ty
- Фронтенд: TypeScript, Vite, React, Mantine, oxlint/oxfmt
- Контракт: TypeSpec → OpenAPI → TypeScript SDK (@hey-api/openapi-ts)
- Окружение и задачи: mise, hk (git-хуки), GitHub Actions

## Установка

```bash
git clone https://github.com/Kamazoh1/ai-for-developers-project-387.git
cd ai-for-developers-project-387
mise install        # инструменты нужных версий
mise run install    # зависимости
mise run hooks      # git-хуки
```

## Использование

```bash
mise daemons start   # бекенд :8000, фронтенд :5173
mise daemons stop
mise run check       # быстрые проверки: линтеры, типы, тесты, сборка
mise run verify      # всё сразу: check + браузерный сценарий e2e (то же самое запускает CI)
```

### Сквозные тесты (e2e)

Один сценарий Playwright в настоящем браузере: гость бронирует слот, второй гость на тот же слот получает «Это время уже занято», владелец видит встречу в `/admin/bookings`. Подмены сети и часов нет.

```bash
mise run install       # зависимости бэкенда и фронтенда (как для остальных задач)
mise run e2e:install   # один раз: пакет e2e и браузер Chromium
mise run e2e           # поднимает бэкенд на временной SQLite-базе и фронтенд на свободных портах, гоняет сценарий, останавливает всё
```

Задача `e2e` входит в `mise run verify` (после `check`) и не входит в быстрый `mise run check`. В CI один job запускает `mise run verify`, поэтому локальный и CI-прогон совпадают. Трейс упавшего теста лежит в `e2e/test-results/`.

### Docker

В корне лежит `Dockerfile`: один образ с API и собранным фронтендом (один процесс, один порт). Приложение слушает порт из переменной окружения **`PORT`** (если её нет, то 10000) и стартует само, без аргументов.

```bash
mise run docker:build                  # docker build -t call-calendar .
PORT=8080 mise run docker:run          # http://localhost:8080
mise run docker:smoke                  # собрать образ, запустить на свободном PORT и прогнать браузерный сценарий
```

**Данные после перезапуска.** Брони и типы событий лежат в файле SQLite внутри контейнера (`DATABASE_PATH=/tmp/call-calendar.db`), поэтому **при перезапуске или пересоздании контейнера они сбрасываются**. Чтобы сохранить их, смонтируйте том и укажите путь на нём в `DATABASE_PATH`.

### Деплой на Render

Публичная ссылка: _появится здесь после первого деплоя_.

Сервис описан в `render.yaml` (Blueprint): Docker, бесплатный план, проверка `/health`, порт из `PORT`. На бесплатном плане **нет постоянного диска**: файловая система стирается при каждом редеплое, перезапуске и засыпании сервиса (через 15 минут без запросов), то есть **все данные сбрасываются**. Первый запрос после простоя идёт около минуты.

Создать сервис можно двумя способами:

1. **Через дашборд:** Render → New → Blueprint → выбрать этот репозиторий. Ключ не нужен.
2. **Через MCP-сервер Render:** конфигурация проекта лежит в `.mcp.json`, ключ в репозиторий не попадает.

   ```bash
   # 1. Ключ: https://dashboard.render.com/u/settings → API Keys → Create API Key.
   # 2. Положите его в переменную окружения до запуска Claude Code (не в файл репозитория):
   read -rs RENDER_API_KEY && export RENDER_API_KEY
   # 3. Запустите Claude Code из корня репозитория и подтвердите проектный MCP-сервер «render».
   claude
   ```

   Ключ Render действует на весь аккаунт: не публикуйте его и не вставляйте в чат. `.env*` игнорируется git.

Проверить опубликованное приложение тем же браузерным сценарием (гость записывается, второй гость получает отказ, владелец видит встречу):

```bash
mise run e2e:url -- https://<имя-сервиса>.onrender.com
```

Сценарий создаёт тип события и бронь в работающем приложении; они пропадут при следующем перезапуске.

### Релизы

Релизы собирает [release-please](https://github.com/googleapis/release-please) из Conventional Commits. Версия одна на весь репозиторий; тег выглядит как `v0.2.0`.

1. После каждого влития в `main` workflow `release-please.yml` открывает (или обновляет) release PR с заголовком вида `chore(main): release 0.2.0`. В нём обновлённый `CHANGELOG.md` и новая версия в `backend/pyproject.toml`, `backend/uv.lock`, `frontend/package.json`, `frontend/package-lock.json`. Версия, с которой release-please считает следующую, хранится в `.release-please-manifest.json`.
2. Версию определяют типы коммитов с прошлого релиза: `fix:` даёт патч, `feat:` — минор (пока версия `0.x`), `!` или `BREAKING CHANGE:` — мажор. Коммиты `chore:`, `docs:`, `ci:` в changelog не попадают и релиз сами не открывают.
3. CI на release PR не запускается: ветку создаёт `GITHUB_TOKEN`, а события от него GitHub не превращает в запуски workflow. Поэтому перед слиянием проверьте ветку вручную, чтобы убедиться, что lock-файлы с новой версией ставятся и всё зелёное:

   ```bash
   git fetch origin release-please--branches--main--components--call-calendar
   git checkout -B release-check FETCH_HEAD
   mise run install && mise run verify
   git checkout main && git branch -D release-check
   ```

4. Слияние release PR создаёт тег и релиз на GitHub с этим changelog. Вручную версии и changelog править не нужно.

Для работы в настройках репозитория (Actions → General) должна быть включена опция «Allow GitHub Actions to create and approve pull requests».

### Агент по `@claude`

Воркфлоу `.github/workflows/claude.yml` запускает [claude-code-action](https://github.com/anthropics/claude-code-action) по комментарию с `@claude` в issue, PR или ревью PR.

- **Событие.** `issue_comment` и `pull_request_review_comment` с `types: [created]`, `pull_request_review` с `types: [submitted]` (у ревью нет типа `created`, `submitted` — тот же момент).
- **Модель.** `claude-sonnet-5-5` (последний Sonnet), задана явно через `--model` в `claude_args`. Ключ лежит в GitHub Secrets: `CLAUDE_CODE_OAUTH_TOKEN`. Менять модель нужно в `claude.yml`.
- **Назначение.** Выполнить задачу из комментария по правилам из `AGENTS.md`: Conventional Commits, контракт `api/main.tsp` меняется первым, перед пушем зелёный `mise run check`. Скиллы (`.claude/skills`) и `docs/agents/` берутся из `main`, инструменты ставятся тем же `mise`, что и в `ci.yml`.
- **Результаты.** Ответный комментарий от `claude[bot]` в том же issue или PR; если задача требует правок, ветка и PR от приложения; прогон виден во вкладке Actions (workflow `claude`).
- **Кто может вызвать.** Только `OWNER`, `MEMBER` и `COLLABORATOR`. Комментарии ботов (в том числе ответы самого агента) под это условие не попадают: у них `author_association` другой. Репозиторий публичный, но форки секретов не получают: воркфлоу работает в контексте основной ветки, код из форка не выполняется.
- **Права и ограничения.** У `GITHUB_TOKEN`: `contents: write`, `pull-requests: write`, `issues: write` (комментарии, ветки и PR), `id-token: write` (обмен OIDC на токен приложения) и `actions: read` (чтобы агент читал результаты CI). Тайм-аут задания 30 минут, один прогон на issue или PR одновременно (новый комментарий ждёт). Агенту разрешены `mise run`, `gh pr`, `gh issue` и `git`.
- **Установка.** Нужно приложение [Claude](https://github.com/apps/claude) на репозитории и секрет `CLAUDE_CODE_OAUTH_TOKEN` (оба настраивает `/install-github-app`).

**Набор команд (mentions).** Агент понимает свободный текст, но в проекте используются три формы:

| Комментарий | Что делает агент |
|---|---|
| `@claude explain this issue` | объясняет issue или PR, ничего не меняет |
| `@claude implement this` / `@claude fix <что>` | правит код, прогоняет `mise run check`, открывает PR |
| `@claude review this PR` | читает дифф и результаты CI, отвечает комментарием |

**Share.** Сессии агента не публикуются: `show_full_output` и `display_report` не включены (в действии они по умолчанию `false`, в `claude.yml` не заданы). Репозиторий публичный, а полный вывод и отчёт содержат результаты инструментов (пути, окружение), поэтому включать их не нужно. Остаются только комментарий агента и ссылка на прогон в Actions.

### Автотриаж issues

Воркфлоу `.github/workflows/triage.yml` разбирает новые issue по правилам скилла `triage` и словарю меток из `docs/agents/triage-labels.md`.

- **Событие.** `issues` с `types: [opened]`. Событий `edited` и `labeled` нет: изменения меток самим агентом не должны запускать его снова.
- **Кто запускает.** Только авторы `OWNER`, `MEMBER` и `COLLABORATOR`, боты исключены. Текст issue считается недоверенным: агент читает его как данные и не выполняет написанные там инструкции.
- **Что не разбирается повторно.** Issue, у которого уже есть метка состояния (`needs-*`, `ready-for-*`, `wontfix`), пропускается. Тикеты, подготовленные скиллами (`to-tickets` публикует их сразу с `ready-for-agent`), поэтому повторно не разбираются. Вторая проверка в prompt: если под issue уже есть комментарий, начинающийся с `> *This was generated by AI during triage.*`, агент ничего не меняет.
- **Что делает агент.** Ставит одну категорию (`bug` или `enhancement`) и `needs-triage`, оставляет один комментарий с рекомендацией (категория, предлагаемое состояние, что в коде относится к делу, нет ли уже реализации). Issue не закрывает и `ready-for-agent`, `ready-for-human`, `wontfix` не ставит: решение остаётся за maintainer'ом.
- **Модель и prompt.** `claude-haiku-5-5` (триажу хватает), prompt задан в `triage.yml`. Ключ: `CLAUDE_CODE_OAUTH_TOKEN` в GitHub Secrets.
- **Ограничения.** Тайм-аут 10 минут, не более 15 шагов агента. Один прогон на issue (`concurrency` по номеру issue): общая группа на все issue оставляла бы в очереди только один запуск, а остальные отменялись бы. Права `GITHUB_TOKEN`: `contents: read`, `issues: write`, `id-token: write`. Агенту разрешены чтение репозитория и `gh issue view`, `gh issue comment`, `gh issue edit`; `git`, `mise` и правка файлов недоступны.
- **Метки.** `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human` должны существовать в репозитории (создаются через `gh label create`, см. `docs/agents/triage-labels.md`).
- **Share.** Как и у `@claude`, сессия не публикуется.

<!-- Добавьте запись asciinema — именно это смотрит работодатель -->

---

<details>
<summary>Автоматические тесты Хекслета</summary>

Тесты запускаются на каждый коммит. За запуск отвечает файл `.github/workflows/hexlet-check.yml` — не удаляйте и не переименовывайте ни его, ни репозиторий.

</details>

## О Хекслете

[Хекслет](https://ru.hexlet.io/) — школа программирования: авторские программы обучения с практикой, поддержкой наставников и реальными проектами, которые остаются в резюме. Этот репозиторий — один из таких проектов.
