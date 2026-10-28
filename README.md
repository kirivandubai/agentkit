# agentkit

Общая библиотека примитивов агентов владельца: agent-os, его исполнители (presentations, video, demos), шаблон
агента `agent-template`, model-gateway. Задача 3 списка `agent-os/docs/reviews/2026-10-28-code-review/next-architecture-reuse.md`
(находки X2-19…X2-22): одна реализация маски секретов и файловых примитивов вместо копий в каждом репозитории.

## Модули

| Модуль | Что | Зависимости |
|---|---|---|
| `agentkit.redact` | Одна маска `MASK = "‹secret›"`; шаблоны записанных учётных данных (`Bearer`/`Basic`, пары `api_key=`, ключи по префиксу `ghp_`, `sk-`, `AKIA`…; `LOOSE` — для текста, уходящего третьей стороне); рецепт `scrub_text(text, keys, cut=)` — ключи вон, шаблоны, потом обрезка; `Redactor(values, min_len=, head_chars=)` — известные значения, пороги параметрами; `env_values` — значения файла `KEY=value` | stdlib |
| `agentkit.safefs` | Обход каталогов через дескрипторы с `O_NOFOLLOW` (`walk`), открытие листа без ссылок и без ожидания FIFO (`open_leaf`, `open_regular`, `create`), чтение с пределом (`read_bounded`, `read_json_bounded`), атомарная запись (`atomic_writer`, `write_atomic`), удаление только обычного файла (`unlink_regular`) | stdlib |

Ядро (`redact`, `safefs`) — только stdlib и Python 3.9: скрипт хоста на `/usr/bin/python3` (снимки досок dev в
agent-os) и бокс hermes-dev берут его копией в `vendor/` с тестом хеша. Тесты на симлинки, FIFO, гонки и пороги маски
живут здесь, один раз.

## Как зависеть

```toml
dependencies = ["agentkit"]

[tool.uv.sources]
agentkit = { git = "https://github.com/kirivandubai/agentkit", tag = "v0.1.0" }
```

Репозиторий приватный: на хосте git берёт ключ через `gh auth git-credential` (`~/.gitconfig`). Сборка Docker-образа
получает его build-секретом `github_token` (compose: `secrets: github_token: environment: GITHUB_TOKEN`; install.sh
ставит `GITHUB_TOKEN` из `gh auth token`), токен не попадает ни в слой, ни в кэш.

Новая версия — новый тег `vX.Y.Z` и `uv lock` в каждом зависящем репозитории; копии в `vendor/` обновляются байт в
байт (их тест хеша иначе падает).

## Разработка

```sh
uv run pytest -q
uv run ruff check
```
