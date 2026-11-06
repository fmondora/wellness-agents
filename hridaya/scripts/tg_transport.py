#!/usr/bin/env python3.12
"""Trasporto Telegram condiviso da bot, server MCP e script di invio.

Solo HTTP verso api.telegram.org (urllib, nessuna dipendenza). Ogni funzione
di invio accetta `call`/`multipart` iniettabili: i test non toccano la rete.

    call(token, method, **params)            → dict (ok) | TelegramError
    multipart(token, method, fields, files)  → dict (ok) | TelegramError
"""
from __future__ import annotations

import json
import mimetypes
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable

API = "https://api.telegram.org/bot{token}/{method}"
MAX_TEXT = 4096
MAX_CAPTION = 1024


class TelegramError(RuntimeError):
    def __init__(self, method: str, code: int | None, description: str):
        super().__init__(f"{method}: {code} {description}")
        self.method, self.code, self.description = method, code, description


def _decode(method: str, raw: bytes) -> dict:
    try:
        out = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        raise TelegramError(method, None, raw[:200].decode("utf-8", "replace"))
    if not out.get("ok"):
        raise TelegramError(method, out.get("error_code"), out.get("description", ""))
    return out


def call(token: str, method: str, _timeout: int = 60, **params: Any) -> dict:
    """POST urlencoded. `_timeout` è quello HTTP; `timeout` (se passato) è il parametro di getUpdates."""
    data = {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
            for k, v in params.items() if v is not None}
    req = urllib.request.Request(API.format(token=token, method=method),
                                 data=urllib.parse.urlencode(data).encode(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=_timeout) as resp:
            return _decode(method, resp.read())
    except urllib.error.HTTPError as e:   # 409 Conflict, 400, 401… con corpo JSON
        body = e.read()
        try:
            j = json.loads(body.decode("utf-8", "replace"))
            raise TelegramError(method, j.get("error_code", e.code), j.get("description", str(e)))
        except ValueError:
            raise TelegramError(method, e.code, str(e))


def multipart(token: str, method: str, fields: dict[str, Any],
              files: dict[str, Path], timeout: int = 120) -> dict:
    boundary = f"----hridaya{uuid.uuid4().hex}"
    body = bytearray()
    for k, v in fields.items():
        if v is None:
            continue
        v = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
        body += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n'.encode()
        body += str(v).encode("utf-8") + b"\r\n"
    for name, path in files.items():
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        body += (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; '
                 f'filename="{path.name}"\r\nContent-Type: {ctype}\r\n\r\n').encode()
        body += path.read_bytes() + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(API.format(token=token, method=method), data=bytes(body),
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return _decode(method, resp.read())
    except urllib.error.HTTPError as e:
        raise TelegramError(method, e.code, e.read()[:300].decode("utf-8", "replace"))


Call = Callable[..., dict]
Multipart = Callable[..., dict]


def chunks(text: str, size: int = MAX_TEXT) -> list[str]:
    """Spezza su righe quando possibile (Telegram tronca a 4096)."""
    out, cur = [], ""
    for line in text.splitlines(keepends=True):
        while len(line) > size:
            if cur:
                out.append(cur)
                cur = ""
            out.append(line[:size])
            line = line[size:]
        if len(cur) + len(line) > size:
            out.append(cur)
            cur = ""
        cur += line
    if cur or not out:
        out.append(cur)
    return out


def send_text(token: str, chat_id: int | str, text: str, parse_mode: str | None = None,
              reply_markup: dict | None = None, call: Call = call) -> list[dict]:
    parts = chunks(text)
    res = []
    for i, part in enumerate(parts):
        res.append(call(token, "sendMessage", chat_id=chat_id, text=part, parse_mode=parse_mode,
                        disable_web_page_preview="true",
                        reply_markup=reply_markup if i == len(parts) - 1 else None))
    return res


def send_card(token: str, chat_id: int | str, steps: list[dict], base: Path,
              call: Call = call, multipart: Multipart = multipart) -> int:
    """Scheda: lista di passi {"text": html} | {"photos": [path...], "caption": html}."""
    n = 0
    for step in steps:
        if "text" in step:
            send_text(token, chat_id, step["text"], parse_mode="HTML", call=call)
        else:
            paths = [Path(p) if Path(p).is_absolute() else base / p for p in step["photos"]]
            cap = (step.get("caption") or "")[:MAX_CAPTION]
            if len(paths) == 1:
                multipart(token, "sendPhoto", {"chat_id": chat_id, "photo": "attach://p0",
                                               "caption": cap, "parse_mode": "HTML"}, {"p0": paths[0]})
            else:
                media = [{"type": "photo", "media": f"attach://p{i}"} for i in range(len(paths))]
                if cap:
                    media[0].update(caption=cap, parse_mode="HTML")
                multipart(token, "sendMediaGroup", {"chat_id": chat_id, "media": media},
                          {f"p{i}": p for i, p in enumerate(paths)})
        n += 1
    return n


def send_file(token: str, chat_id: int | str, path: Path, caption: str = "",
              multipart: Multipart = multipart) -> dict:
    return multipart(token, "sendDocument", {"chat_id": chat_id, "caption": caption[:MAX_CAPTION] or None},
                     {"document": path})
