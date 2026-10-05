import asyncio
import hmac
import json
import os
import sqlite3
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel

from read_tools import TOOL_SCHEMAS, execute_tool


OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434").rstrip("/")
MODEL = os.getenv("QWEN_MODEL", "qwen3.5:4b-q4_K_M")
DB_PATH = Path(os.getenv("AGENT_DB_PATH", "/data/agent.db"))
WEB_USER = os.getenv("AGENT_WEB_USER", "igor")
WEB_PASSWORD = os.getenv("AGENT_WEB_PASSWORD", "")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
HISTORY_MESSAGES = max(4, int(os.getenv("AGENT_HISTORY_MESSAGES", "8")))
QWEN_THINK = os.getenv("QWEN_THINK", "false").strip().lower() in {"1", "true", "yes", "on"}
READ_TOOLS_ENABLED = os.getenv("AGENT_READ_TOOLS", "false").strip().lower() in {"1", "true", "yes", "on"}
MAX_TOOL_ROUNDS = 4
TOOL_RESULT_CHARS = max(1000, int(os.getenv("AGENT_TOOL_RESULT_CHARS", "3500")))

SYSTEM_PROMPT = os.getenv(
    "AGENT_SYSTEM_PROMPT",
    (
        "Ты Server AI Agent — локальная модель Qwen, запущенная на домашнем Ubuntu-сервере пользователя. "
        "Не утверждай, что работаешь в облаке. Отвечай по-русски, если пользователь не попросил иначе. "
        "Будь точным и не выдумывай результаты проверок. "
        + (
            "У тебя включён READ-режим: ты можешь самостоятельно использовать доступные инструменты для чтения "
            "файлов, поиска по разрешённым каталогам, просмотра systemd/journal, Docker, сети, дисков, GPU, "
            "процессов и Git-статуса. Используй инструменты, когда вопрос требует фактической проверки сервера. "
            "Для общей проверки состояния сервера сначала используй server_health: он возвращает компактный отчёт одним вызовом. "
            "Никогда не проси пользователя вручную выполнить диагностическую команду, если нужные данные можно "
            "получить READ-инструментом. Не пытайся раскрывать пароли, токены, приватные ключи или другие секреты. "
            "READ-режим не умеет менять файлы, перезапускать службы, выполнять произвольный shell или админ-действия. "
            "Если просят что-то изменить, сначала проведи доступную диагностику и объясни, что запись/ADMIN ещё не включены."
            if READ_TOOLS_ENABLED
            else
            "READ-инструменты сейчас отключены. Файловый доступ, shell, Git и серверная диагностика недоступны."
        )
    ),
)

STRICT_GROUNDING_PROMPT = (
    SYSTEM_PROMPT
    + " ВАЖНО ДЛЯ ТЕКУЩЕЙ ДИАГНОСТИКИ: после вызова READ-инструментов все утверждения "
      "о текущем состоянии сервера должны опираться только на результаты инструментов ЭТОГО запроса. "
      "Не используй числа, списки контейнеров, uptime, версии, статусы или другие текущие значения из памяти "
      "модели либо из предыдущей истории чата. Числа, имена и статусы переноси из tool-result точно, без "
      "самовольного исправления или дополнения. Если нужный параметр инструментом не проверялся, напиши "
      "«не проверено». Если инструмент вернул ошибку, укажи ошибку и не подменяй её предположением. "
      "Можно делать выводы, но явно отделяй их от наблюдаемых данных. "
      "Отвечай на русском языке. Не смешивай русский с украинским или другими языками, если пользователь этого не просил. "
      "Для структурированных полей *_bytes можешь переводить значения в GiB/MiB, но не меняй проценты, имена и статусы. "
      "Если server_health содержит поля docker/docker_count и failed_systemd/failed_systemd_count, обязательно отрази их в ответе; "
      "не заявляй, что этих данных нет, если они присутствуют в tool-result."
)

security = HTTPBasic(auto_error=False)
model_lock = asyncio.Lock()


def parse_allowed_ids() -> set[int]:
    raw = os.getenv("TELEGRAM_ALLOWED_USER_IDS", "")
    result: set[int] = set()
    for item in raw.replace(";", ",").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            result.add(int(item))
        except ValueError:
            raise RuntimeError("TELEGRAM_ALLOWED_USER_IDS must contain numeric Telegram user IDs")
    return result


ALLOWED_TELEGRAM_IDS = parse_allowed_ids()


def connect_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with connect_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.commit()


def add_message(role: str, content: str, source: str) -> int:
    with connect_db() as conn:
        cur = conn.execute(
            "INSERT INTO messages(role, content, source) VALUES (?, ?, ?)",
            (role, content, source),
        )
        conn.commit()
        return int(cur.lastrowid)


def list_messages(limit: int = 200) -> list[dict]:
    with connect_db() as conn:
        rows = conn.execute(
            """
            SELECT id, role, content, source, created_at
            FROM messages
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


def model_history() -> list[dict]:
    messages = list_messages(HISTORY_MESSAGES)
    return [{"role": m["role"], "content": m["content"]} for m in messages]


def clear_messages() -> None:
    with connect_db() as conn:
        conn.execute("DELETE FROM messages")
        conn.commit()


def require_auth(
    credentials: Annotated[HTTPBasicCredentials | None, Depends(security)],
) -> str:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Basic"},
        )
    good_user = hmac.compare_digest(credentials.username, WEB_USER)
    good_password = hmac.compare_digest(credentials.password, WEB_PASSWORD)
    if not (good_user and good_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


def _tool_label(name: str, arguments: dict) -> str:
    if name == "systemd_status":
        return f"systemd_status({arguments.get('unit', '?')})"
    if name == "journal":
        unit = arguments.get("unit") or "all"
        minutes = arguments.get("minutes", 60)
        return f"journal({unit}, {minutes}m)"
    if name == "docker_logs":
        return f"docker_logs({arguments.get('container', '?')})"
    if name == "git_status":
        return f"git_status({arguments.get('path', '?')})"
    if name in {"read_text_file", "list_files", "find_files", "search_text"}:
        return f"{name}({arguments.get('path', '?')})"
    if name == "server_snapshot":
        return f"server_snapshot({arguments.get('section', '?')})"
    return name


def _compact_tool_content(result: dict) -> str:
    raw = json.dumps(result, ensure_ascii=False)
    if len(raw) <= TOOL_RESULT_CHARS:
        return raw
    return raw[:TOOL_RESULT_CHARS] + f"...[truncated {len(raw) - TOOL_RESULT_CHARS} chars]"


def _normalize_tool_arguments(value) -> dict:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("Tool arguments must be an object")


async def ask_model(user_text: str, source: str) -> str:
    text = user_text.strip()
    if not text:
        raise ValueError("Empty message")

    async with model_lock:
        add_message("user", text, source)
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, *model_history()]
        grounded_messages = [
            {"role": "system", "content": STRICT_GROUNDING_PROMPT},
            {"role": "user", "content": text},
        ]
        tool_trace: list[str] = []
        grounded_mode = False
        answer = ""

        try:
            async with httpx.AsyncClient(timeout=240.0) as client:
                for _ in range(MAX_TOOL_ROUNDS):
                    active_messages = grounded_messages if grounded_mode else messages
                    payload = {
                        "model": MODEL,
                        "messages": active_messages,
                        "stream": False,
                        "think": QWEN_THINK,
                        "keep_alive": "10m",
                    }
                    if READ_TOOLS_ENABLED:
                        payload["tools"] = TOOL_SCHEMAS

                    response = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
                    response.raise_for_status()
                    data = response.json()
                    message = data.get("message") or {}
                    tool_calls = message.get("tool_calls") or []

                    if not tool_calls:
                        answer = str(message.get("content") or "").strip()
                        break

                    # As soon as a READ tool is used, drop old chat history from
                    # the synthesis context. Only the current user request and
                    # tool evidence from this turn remain authoritative.
                    if not grounded_mode:
                        grounded_mode = True
                    grounded_messages.append(message)

                    for call in tool_calls:
                        function = call.get("function") or {}
                        name = str(function.get("name") or "")
                        started = time.monotonic()
                        try:
                            arguments = _normalize_tool_arguments(function.get("arguments"))
                            print(f"[READ] tool={name} argument_keys={sorted(arguments.keys())}", flush=True)
                            result = await asyncio.to_thread(execute_tool, name, arguments)
                        except Exception as exc:
                            arguments = {}
                            result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

                        elapsed = time.monotonic() - started
                        tool_content = _compact_tool_content(result)
                        label = _tool_label(name, arguments)
                        tool_trace.append(label)
                        print(
                            f"[READ] tool={name} elapsed={elapsed:.2f}s result_chars={len(tool_content)}",
                            flush=True,
                        )

                        grounded_messages.append(
                            {
                                "role": "tool",
                                "tool_name": name,
                                "content": tool_content,
                            }
                        )
                else:
                    answer = "Достигнут лимит READ-вызовов за один запрос. Уточни задачу или сузь область проверки."

                if not answer:
                    answer = "Модель вернула пустой итоговый ответ после READ-проверки. Повтори запрос или уточни задачу."

                if tool_trace:
                    checked = ", ".join(dict.fromkeys(tool_trace))
                    answer = answer.rstrip() + f"\n\nПроверено инструментами: {checked}."
        except Exception as exc:
            answer = f"Ошибка обращения к локальной модели/READ-инструментам: {type(exc).__name__}: {exc}"

        add_message("assistant", answer, "agent")
        return answer


async def ollama_ok() -> bool:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{OLLAMA_URL}/api/tags")
            return response.is_success
    except Exception:
        return False


async def telegram_api(method: str, payload: dict | None = None) -> dict:
    if not TELEGRAM_TOKEN:
        return {}
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}"
    async with httpx.AsyncClient(timeout=65.0) as client:
        response = await client.post(url, json=payload or {})
        response.raise_for_status()
        return response.json()


async def telegram_send(chat_id: int, text: str) -> None:
    remaining = text or "(пустой ответ)"
    while remaining:
        chunk = remaining[:3900]
        remaining = remaining[3900:]
        await telegram_api(
            "sendMessage",
            {"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True},
        )


async def telegram_loop() -> None:
    if not TELEGRAM_TOKEN:
        return
    if not ALLOWED_TELEGRAM_IDS:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is set but TELEGRAM_ALLOWED_USER_IDS is empty"
        )

    offset = 0
    while True:
        try:
            result = await telegram_api(
                "getUpdates",
                {
                    "offset": offset,
                    "timeout": 50,
                    "allowed_updates": ["message"],
                },
            )
            for update in result.get("result", []):
                offset = max(offset, int(update["update_id"]) + 1)
                message = update.get("message") or {}
                sender = message.get("from") or {}
                user_id = sender.get("id")
                chat_id = message.get("chat", {}).get("id")
                text = (message.get("text") or "").strip()

                if not isinstance(user_id, int) or not isinstance(chat_id, int):
                    continue
                if user_id not in ALLOWED_TELEGRAM_IDS:
                    continue
                if not text:
                    await telegram_send(chat_id, "Пока поддерживаются текстовые сообщения.")
                    continue

                if text == "/start":
                    await telegram_send(
                        chat_id,
                        f"Server AI Agent запущен локально. Модель: {MODEL}. "
                        "История общая с веб-панелью.",
                    )
                    continue
                if text == "/status":
                    state = "OK" if await ollama_ok() else "ERROR"
                    tools_state = "ON" if READ_TOOLS_ENABLED and Path("/run/server-ai/read.sock").exists() else "OFF"
                    await telegram_send(chat_id, f"Ollama: {state}\nМодель: {MODEL}\nREAD tools: {tools_state}\nGrounding: STRICT")
                    continue
                if text == "/new":
                    clear_messages()
                    await telegram_send(chat_id, "Общая история диалога очищена.")
                    continue

                await telegram_send(chat_id, "Принял. Думаю…")
                answer = await ask_model(text, "telegram")
                await telegram_send(chat_id, answer)
        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not WEB_PASSWORD or WEB_PASSWORD.startswith("CHANGE_ME"):
        raise RuntimeError("Set a strong AGENT_WEB_PASSWORD in server-ai/.env")
    init_db()
    telegram_task = asyncio.create_task(telegram_loop())
    try:
        yield
    finally:
        telegram_task.cancel()
        await asyncio.gather(telegram_task, return_exceptions=True)


app = FastAPI(title="Server AI Agent", version="0.1.0", lifespan=lifespan)


class ChatRequest(BaseModel):
    message: str


@app.get("/health")
async def health() -> dict:
    return {
        "ok": True,
        "ollama": await ollama_ok(),
        "model": MODEL,
        "telegram": bool(TELEGRAM_TOKEN),
        "read_tools": READ_TOOLS_ENABLED and Path("/run/server-ai/read.sock").exists(),
        "strict_grounding": True,
    }


@app.get("/")
async def index(_: Annotated[str, Depends(require_auth)]):
    return FileResponse("/app/web/index.html")


@app.get("/api/messages")
async def messages(_: Annotated[str, Depends(require_auth)]) -> dict:
    return {"messages": list_messages()}


@app.post("/api/chat")
async def chat(
    request: ChatRequest,
    _: Annotated[str, Depends(require_auth)],
) -> dict:
    try:
        answer = await ask_model(request.message, "web")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"answer": answer}


@app.post("/api/new")
async def new_chat(_: Annotated[str, Depends(require_auth)]) -> dict:
    clear_messages()
    return {"ok": True}
