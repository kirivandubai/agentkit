# agentkit

Общая библиотека примитивов агентов владельца: agent-os, его исполнители (presentations, video, demos), шаблон
агента `agent-template`, model-gateway. Задача 3 списка `agent-os/docs/reviews/2026-10-28-code-review/next-architecture-reuse.md`
(находки X2-19…X2-22): одна реализация маски секретов и файловых примитивов вместо копий в каждом репозитории.

## Модули

| Модуль | Что | Зависимости |
|---|---|---|
| `agentkit.redact` | Одна маска `MASK = "‹secret›"`; шаблоны записанных учётных данных (`Bearer`/`Basic`, пары `api_key=`, ключи по префиксу `ghp_`, `sk-`, `AKIA`…; `LOOSE` — для текста, уходящего третьей стороне); рецепт `scrub_text(text, keys, cut=)` — ключи вон, шаблоны, потом обрезка; `Redactor(values, min_len=, head_chars=)` — известные значения, пороги параметрами; `env_values` — значения файла `KEY=value` | stdlib |
| `agentkit.fetch` | HTTP-клиент кода агента: без редиректов (3xx — ответ), без прокси окружения, тело с пределом, текст отказа без адреса и заголовков (`fetch`, `FetchFailed`); `is_public(address)` — проверка адреса, выбранного моделью (SSRF). Названо не `http`, чтобы копия в `vendor/` не подменила пакет stdlib | stdlib |
| `agentkit.sqlite` | `open_ro(path, timeout=)` — чтение базы, которую пишет кто-то другой: `mode=ro`, путь как file: URI | stdlib |
| `agentkit.mcp` | Каркас MCP-сервера исполнителя (стандарт агента agent-os, §4): `build_server` с обязательной защитой Host, `host_names`, ошибки `AgentError`/`Refused`/`Unavailable`/`ConfigError`, обёртки `guarded`/`guarded_async` (своё дерево ошибок сервера — параметр `sentences`) | `agentkit[mcp]` |
| `agentkit.safefs` | Обход каталогов через дескрипторы с `O_NOFOLLOW` (`walk`), открытие листа без ссылок и без ожидания FIFO (`open_leaf`, `open_regular`, `create`), чтение с пределом (`read_bounded`, `read_json_bounded`), атомарная запись (`atomic_writer`, `write_atomic`), удаление только обычного файла (`unlink_regular`) | stdlib |

Ядро (`redact`, `safefs`, `fetch`, `sqlite`) — только stdlib и Python 3.9: скрипт хоста на `/usr/bin/python3` (снимки досок dev в
agent-os) и бокс hermes-dev берут его копией в `vendor/` с тестом хеша. Тесты на симлинки, FIFO, гонки и пороги маски
живут здесь, один раз.

## Как зависеть

```toml
dependencies = ["agentkit"]            # или "agentkit[mcp]" для tool-сервера

[tool.uv.sources]
agentkit = { git = "https://github.com/kirivandubai/agentkit", tag = "v0.1.0" }
```

Репозиторий публичный (владелец, 2026-10-28): `uv sync` и сборке Docker-образа нужен только доступ к github.com —
ни токена, ни build-секрета. Где github.com недоступен при сборке (образ коробки dev), библиотека лежит копией в
`vendor/` по тегу.

Новая версия — новый тег `vX.Y.Z` и `uv lock` в каждом зависящем репозитории; копии в `vendor/` обновляются байт в
байт (их тест хеша иначе падает).

## Разработка

```sh
uv run pytest -q
uv run ruff check
```
