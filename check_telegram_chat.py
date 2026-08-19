"""Telegram chat ID'sinden erişilebilen sohbet bilgilerini gösterir."""

from __future__ import annotations

import argparse
import math
import os
import re
import sys
from collections.abc import Iterable, Mapping
from typing import Any

import requests

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    # Lambda/üretim ortamında python-dotenv bulunmayabilir; ortam değişkeni yeterlidir.
    pass


TELEGRAM_API_URL = "https://api.telegram.org"
CHAT_ID_PATTERN = re.compile(r"^-?[0-9]+$")


class TelegramLookupError(RuntimeError):
    """Telegram API sorgusu tamamlanamadığında yükseltilir."""


def normalize_chat_id(value: str) -> str:
    """Pozitif/negatif sayısal Telegram chat ID'sini doğrular."""
    chat_id = value.strip()
    if not CHAT_ID_PATTERN.fullmatch(chat_id) or int(chat_id) == 0:
        raise ValueError("Chat ID sıfır olmayan sayısal bir değer olmalıdır (ör. 123 veya -100123).")
    return chat_id


def parse_chat_ids(values: Iterable[str]) -> list[str]:
    """Virgül/noktalı virgülle ayrılmış ID'leri doğrular ve tekilleştirir."""
    chat_ids: list[str] = []
    seen: set[str] = set()
    for value in values:
        for part in value.replace(";", ",").split(","):
            if not part.strip():
                continue
            chat_id = normalize_chat_id(part)
            if chat_id not in seen:
                chat_ids.append(chat_id)
                seen.add(chat_id)
    return chat_ids


def get_chat(token: str, chat_id: str, timeout: float = 10.0) -> dict[str, Any]:
    """Bot API getChat metodunu çağırıp ChatFullInfo sonucunu döndürür."""
    url = f"{TELEGRAM_API_URL}/bot{token}/getChat"
    try:
        response = requests.post(
            url,
            data={"chat_id": chat_id},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        # requests hata metni istek URL'sini (dolayısıyla bot token'ını) içerebilir.
        raise TelegramLookupError(
            f"Telegram'a bağlanılamadı ({type(exc).__name__})."
        ) from None

    try:
        payload = response.json()
    except ValueError as exc:
        raise TelegramLookupError(
            f"Telegram geçersiz bir yanıt döndürdü (HTTP {response.status_code})."
        ) from exc

    if not isinstance(payload, Mapping):
        raise TelegramLookupError("Telegram yanıtı beklenen JSON nesnesi biçiminde değil.")

    if not response.ok or payload.get("ok") is not True:
        error_code = payload.get("error_code", response.status_code)
        description = payload.get("description", "Bilinmeyen Telegram API hatası")
        raise TelegramLookupError(f"Telegram API hatası {error_code}: {description}")

    chat = payload.get("result")
    if not isinstance(chat, dict):
        raise TelegramLookupError("Telegram yanıtında sohbet bilgisi bulunamadı.")
    return chat


def extract_usernames(chat: Mapping[str, Any]) -> list[str]:
    """Birincil ve diğer aktif username'leri sırasını koruyarak birleştirir."""
    candidates: list[Any] = [chat.get("username")]
    active_usernames = chat.get("active_usernames")
    if isinstance(active_usernames, list):
        candidates.extend(active_usernames)

    usernames: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        username = candidate.strip().lstrip("@")
        key = username.casefold()
        if username and key not in seen:
            usernames.append(username)
            seen.add(key)
    return usernames


def chat_display_name(chat: Mapping[str, Any]) -> str | None:
    """Özel sohbetlerde ad-soyad, grup/kanallarda başlık üretir."""
    title = chat.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()

    name_parts = [chat.get("first_name"), chat.get("last_name")]
    name = " ".join(part.strip() for part in name_parts if isinstance(part, str) and part.strip())
    return name or None


def format_chat(chat: Mapping[str, Any]) -> str:
    """Sohbet bilgisini terminal için okunabilir hale getirir."""
    chat_types = {
        "private": "özel sohbet",
        "group": "grup",
        "supergroup": "süpergrup",
        "channel": "kanal",
    }
    raw_type = chat.get("type")
    type_label = chat_types.get(raw_type, str(raw_type or "bilinmiyor"))
    lines = [f"Chat ID: {chat.get('id', 'bilinmiyor')}", f"Tür: {type_label}"]

    display_name = chat_display_name(chat)
    if display_name:
        lines.append(f"Görünen ad: {display_name}")

    usernames = extract_usernames(chat)
    if usernames:
        lines.append("Username: " + ", ".join(f"@{username}" for username in usernames))
    else:
        lines.append("Username: bulunamadı (bu sohbet için tanımlı olmayabilir)")
    return "\n".join(lines)


def positive_timeout(value: str) -> float:
    timeout = float(value)
    if not math.isfinite(timeout) or timeout <= 0:
        raise argparse.ArgumentTypeError("timeout sonlu ve sıfırdan büyük olmalıdır")
    return timeout


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            ".env içindeki TELEGRAM_CHAT_ID listesini veya komutta verilen ID'leri "
            "sorgulayıp username'lerini gösterir."
        )
    )
    parser.add_argument(
        "chat_ids",
        nargs="*",
        help="İsteğe bağlı sayısal chat ID'ler; verilmezse TELEGRAM_CHAT_ID kullanılır",
    )
    parser.add_argument(
        "--timeout",
        type=positive_timeout,
        default=10.0,
        help="İstek zaman aşımı (varsayılan: 10 saniye)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    raw_chat_ids = args.chat_ids or [os.getenv("TELEGRAM_CHAT_ID", "")]

    try:
        chat_ids = parse_chat_ids(raw_chat_ids)
    except ValueError as exc:
        print(f"Hata: {exc}", file=sys.stderr)
        return 2

    if not chat_ids:
        print(
            "Hata: TELEGRAM_CHAT_ID .env dosyasında tanımlı değil veya hiç ID içermiyor.",
            file=sys.stderr,
        )
        return 2

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("Hata: TELEGRAM_BOT_TOKEN .env dosyasında veya ortam değişkenlerinde tanımlı değil.", file=sys.stderr)
        return 2

    failed = 0
    for index, chat_id in enumerate(chat_ids, start=1):
        if len(chat_ids) > 1:
            print(f"\n[{index}/{len(chat_ids)}] Sorgulanan ID: {chat_id}")
        try:
            chat = get_chat(token, chat_id, timeout=args.timeout)
        except TelegramLookupError as exc:
            failed += 1
            print(f"Chat ID {chat_id} — Hata: {exc}", file=sys.stderr)
            continue
        print(format_chat(chat))

    if failed:
        print(
            f"\n{len(chat_ids) - failed}/{len(chat_ids)} sohbet başarıyla sorgulandı. "
            "Bot yalnızca tanıdığı veya erişebildiği sohbetleri görebilir.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
