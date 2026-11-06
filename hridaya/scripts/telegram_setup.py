#!/usr/bin/env python3.12
"""Bootstrap guidato del canale Telegram di Hṛdaya (lo usa la skill `setup`).

Un passo per comando, ognuno idempotente. Repo dati: cwd o WELLNESS_DATA.

  token-store [--from-env] [--remove-from-env]
        custodisce il token nel portachiavi macOS (servizio wellness-agents.telegram).
        Senza --from-env lo legge da stdin (incollato, mai in argv né in chat).
        --from-env migra il token che oggi sta nel .env; --remove-from-env poi lo toglie
        dal .env e scrive TELEGRAM_TOKEN_SOURCE=keychain. Fuori da macOS: resta nel .env.
  check [--skip-poll]
        getMe (chi è il bot), getWebhookInfo (deve essere vuoto: un webhook ruba i messaggi),
        getUpdates senza 409 (nessun altro processo legge lo stesso token). Col bot già acceso
        il probe va saltato (--skip-poll): darebbe 409 contro sé stesso.
  wait-start [--seconds 120] [--register]
        aspetta un /start, mostra chi l'ha mandato; con --register lo scrive come unico
        ALLOWED_CHAT_IDS e risponde sul canale.
  commands
        pubblica il menu comandi (setMyCommands).
  launchd --label L --shim PATH [--python P] [--install]
        genera il plist dell'avvio automatico del bot (KeepAlive) che lancia lo shim del
        repo dati; con --install lo scrive in ~/Library/LaunchAgents (il load lo fa la skill).
"""
from __future__ import annotations

import argparse
import getpass
import platform
import plistlib
import sys
import time
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

import channel_config as cc  # noqa: E402
import tg_transport as tt  # noqa: E402


def store_token(token: str, root: Path | None = None, remove_from_env: bool = False,
                runner=None, system: str | None = None) -> str:
    """→ 'keychain' | 'env'. Verifica la rilettura prima di togliere il token dal .env."""
    import subprocess
    runner = runner or subprocess.run
    token = token.strip()
    if not token or ":" not in token:
        raise ValueError("questo non sembra un token di BotFather (formato 123456:ABC…)")
    if (system or platform.system()) == "Darwin":
        account = cc.keychain_account(root=root)
        if cc.keychain_set(account, token, runner) and cc.keychain_get(account, runner) == token:
            cc.set_env_value("TELEGRAM_TOKEN_SOURCE", "keychain", root)
            if not cc.load_env(root).get("TELEGRAM_KEYCHAIN_ACCOUNT"):
                cc.set_env_value("TELEGRAM_KEYCHAIN_ACCOUNT", account, root)
            if remove_from_env:
                cc.set_env_value("TELEGRAM_BOT_TOKEN", None, root)
                cc.set_env_value("TELEGRAM_TOKEN", None, root)
            return "keychain"
    cc.set_env_value("TELEGRAM_BOT_TOKEN", token, root)
    return "env"


def check(token: str, call: Callable[..., dict] = tt.call, poll: bool = True) -> dict:
    out: dict = {}
    me = call(token, "getMe")["result"]
    out["bot"] = f"@{me.get('username')} ({me.get('first_name')})"
    wh = call(token, "getWebhookInfo")["result"]
    out["webhook"] = wh.get("url") or ""
    out["webhook_ok"] = not wh.get("url")
    if poll:
        try:
            call(token, "getUpdates", timeout=0, limit=1)
            out["poll_ok"] = True
        except tt.TelegramError as e:
            out["poll_ok"] = False
            out["poll_error"] = f"{e.code} {e.description}"
            out["conflict"] = e.code == 409
    return out


def wait_start(token: str, seconds: int = 120, call: Callable[..., dict] = tt.call,
               sleep: Callable[[float], None] = time.sleep) -> dict | None:
    offset, deadline = 0, time.monotonic() + seconds
    while time.monotonic() < deadline:
        for upd in call(token, "getUpdates", timeout=10, offset=offset, _timeout=30).get("result") or []:
            offset = max(offset, upd["update_id"] + 1)
            msg = upd.get("message") or {}
            if (msg.get("text") or "").startswith("/start") and (msg.get("chat") or {}).get("type") == "private":
                call(token, "getUpdates", offset=offset, timeout=0)   # conferma: non lo rilegge il bot
                c = msg["chat"]
                return {"id": c["id"], "name": c.get("first_name", ""), "username": c.get("username", "")}
        sleep(1)
    return None


def register_chat(chat_id: int, token: str, root: Path | None = None,
                  call: Callable[..., dict] = tt.call) -> None:
    cc.set_env_value("ALLOWED_CHAT_IDS", str(chat_id), root)
    tt.send_text(token, chat_id, "🫀 Ciao, sono Hṛdaya. Questo canale ora è nostro: "
                                 "solo tu puoi scrivermi qui.", call=call)


def launchd_plist(label: str, shim: Path, python: str, data_root: Path) -> bytes:
    logs = data_root / "data" / "telegram"
    return plistlib.dumps({
        "Label": label,
        "ProgramArguments": [python, str(shim)],
        "WorkingDirectory": str(data_root),
        "EnvironmentVariables": {"WELLNESS_DATA": str(data_root),
                                 "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"},
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 30,
        "StandardOutPath": str(logs / "bot.log"),
        "StandardErrorPath": str(logs / "bot.err.log"),
    })


def main() -> int:
    ap = argparse.ArgumentParser(description="Bootstrap del canale Telegram di Hṛdaya")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("token-store")
    t.add_argument("--from-env", action="store_true")
    t.add_argument("--remove-from-env", action="store_true")
    c = sub.add_parser("check")
    c.add_argument("--skip-poll", action="store_true")
    w = sub.add_parser("wait-start")
    w.add_argument("--seconds", type=int, default=120)
    w.add_argument("--register", action="store_true")
    sub.add_parser("commands")
    ld = sub.add_parser("launchd")
    ld.add_argument("--label", default="com.wellness.hridaya.telegram")
    ld.add_argument("--shim", required=True, help="scripts/telegram_bot.py del repo dati (shim)")
    ld.add_argument("--python", default="/opt/homebrew/bin/python3.12")
    ld.add_argument("--install", action="store_true")
    a = ap.parse_args()
    cc.apply_ca_bundle()

    if a.cmd == "token-store":
        if a.from_env:
            env = cc.load_env()
            token = env.get("TELEGRAM_BOT_TOKEN") or env.get("TELEGRAM_TOKEN") or ""
            if not token:
                sys.exit("Nessun token nel .env da migrare")
        else:
            token = getpass.getpass("Token di BotFather (non viene mostrato): ") if sys.stdin.isatty() \
                else sys.stdin.readline()
        where = store_token(token, remove_from_env=a.remove_from_env)
        print("Token custodito nel portachiavi macOS." if where == "keychain"
              else "Portachiavi non disponibile: token nel .env (che resta fuori da git).")
        return 0
    if a.cmd == "launchd":
        root = cc.data_root().resolve()
        data = launchd_plist(a.label, Path(a.shim).resolve(), a.python, root)
        if a.install:
            dest = Path.home() / "Library" / "LaunchAgents" / f"{a.label}.plist"
            dest.write_bytes(data)
            print(f"scritto {dest} — avvio: launchctl bootstrap gui/$(id -u) {dest}")
        else:
            sys.stdout.write(data.decode())
        return 0

    token = cc.bot_token()
    if not token:
        sys.exit("Manca il token: prima token-store")
    if a.cmd == "check":
        r = check(token, poll=not a.skip_poll)
        print(f"Bot: {r['bot']}")
        print("Webhook: nessuno ✓" if r["webhook_ok"] else
              f"Webhook attivo ({r['webhook']}): ruba i messaggi al long polling — deleteWebhook")
        if "poll_ok" in r:
            print("getUpdates: nessun altro lettore ✓" if r["poll_ok"] else
                  f"getUpdates: {r['poll_error']}" + (" — un altro processo usa questo token" if r.get("conflict") else ""))
        return 0 if r["webhook_ok"] and r.get("poll_ok", True) else 2
    if a.cmd == "wait-start":
        print(f"Aspetto un /start al bot per {a.seconds} s…")
        who = wait_start(token, a.seconds)
        if not who:
            print("Nessun /start ricevuto.")
            return 1
        print(f"/start da {who['name']} @{who['username']} — chat_id {who['id']}")
        if a.register:
            register_chat(who["id"], token)
            print("Registrato come unico ALLOWED_CHAT_IDS; conferma inviata sul canale.")
        return 0
    if a.cmd == "commands":
        import workout_player as wp
        wp.set_bot_commands(token)
        print("Menu comandi pubblicato.")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
