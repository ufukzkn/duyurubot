"""Ham Telegram Chat ID satırlarını ad/username bilgisiyle etiketler."""

from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path

from check_telegram_chat import (
    TelegramLookupError,
    chat_display_name,
    extract_usernames,
    get_chat,
    normalize_chat_id,
)


ROOT = Path(__file__).resolve().parent
CANDIDATE_FILE = ROOT / "telegram_id_candidates.txt"


def raw_candidate_count(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(
        1
        for raw_line in path.read_text(encoding="utf-8-sig").splitlines()
        if raw_line.strip()
        and not raw_line.lstrip().startswith("#")
        and "=" not in raw_line
    )


def label_for_chat(chat: dict, chat_id: str) -> str:
    usernames = extract_usernames(chat)
    if usernames:
        label = f"@{usernames[0]}"
    else:
        label = chat_display_name(chat) or f"Chat {chat_id}"

    label = " ".join(label.replace("=", "-").split())
    if not label:
        label = f"Chat {chat_id}"
    if label.startswith("#"):
        label = f"Telegram {label}"
    return label


def parse_candidate_file(
    path: Path, token: str, timeout: float = 10.0
) -> tuple[int, list[str]]:
    raw = path.read_bytes()
    has_bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    newline = "\r\n" if "\r\n" in text else "\n"
    had_final_newline = text.endswith(("\n", "\r"))
    output: list[str] = []
    errors: list[str] = []
    converted = 0

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" in line:
            output.append(raw_line)
            continue

        try:
            chat_id = normalize_chat_id(line)
        except ValueError as exc:
            errors.append(f"Satır {line_number}: {exc}")
            output.append(raw_line)
            continue

        try:
            chat = get_chat(token, chat_id, timeout=timeout)
        except TelegramLookupError as exc:
            errors.append(f"{chat_id}: {exc}")
            output.append(raw_line)
            continue

        output.append(f"{label_for_chat(chat, chat_id)}={chat_id}")
        converted += 1

    if converted:
        updated = newline.join(output)
        if had_final_newline:
            updated += newline
        encoded = updated.encode("utf-8")
        if has_bom:
            encoded = b"\xef\xbb\xbf" + encoded

        temporary = path.with_name(f"{path.name}.parse.tmp")
        try:
            temporary.write_bytes(encoded)
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

    return converted, errors


def positive_timeout(value: str) -> float:
    timeout = float(value)
    if not math.isfinite(timeout) or timeout <= 0:
        raise argparse.ArgumentTypeError("timeout sonlu ve sıfırdan büyük olmalıdır")
    return timeout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "telegram_id_candidates.txt içindeki ham ID satırlarını "
            "@username=id biçimine dönüştürür."
        )
    )
    parser.add_argument("--timeout", type=positive_timeout, default=10.0)
    args = parser.parse_args(argv)

    if not CANDIDATE_FILE.exists():
        print(f"Hata: {CANDIDATE_FILE.name} bulunamadı.", file=sys.stderr)
        return 1

    raw_count = raw_candidate_count(CANDIDATE_FILE)
    if not raw_count:
        print("Dönüştürülecek ham ID yok; dosya zaten düzenlenmiş.")
        return 0

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("Hata: TELEGRAM_BOT_TOKEN .env dosyasında tanımlı değil.", file=sys.stderr)
        return 1

    try:
        converted, errors = parse_candidate_file(
            CANDIDATE_FILE, token, timeout=args.timeout
        )
    except (OSError, UnicodeError) as exc:
        print(f"Hata: {exc}", file=sys.stderr)
        return 1

    print(f"{converted}/{raw_count} ham ID isimlendirilerek kaydedildi.")
    for error in errors:
        print(f"Uyarı: {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
