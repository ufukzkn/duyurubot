"""Aday Telegram Chat ID'lerini terminalden seçip .env dosyasına kaydeder."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from check_telegram_chat import TelegramLookupError, get_chat
from parse_telegram_candidates import parse_candidate_file, raw_candidate_count
from parse_telegram_candidates import label_for_chat


ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
CANDIDATE_FILE = ROOT / "telegram_id_candidates.txt"
ENV_KEY = "TELEGRAM_CHAT_ID"
CHAT_ID_PATTERN = re.compile(r"^-?[0-9]+$")
ENV_LINE_PATTERN = re.compile(r"^\s*(?:export\s+)?TELEGRAM_CHAT_ID\s*=")


def validate_chat_id(value: str) -> str:
    chat_id = value.strip()
    if not CHAT_ID_PATTERN.fullmatch(chat_id) or int(chat_id) == 0:
        raise ValueError(f"geçersiz Chat ID: {value!r}")
    return chat_id


def split_chat_ids(value: str) -> list[str]:
    chat_ids: list[str] = []
    seen: set[str] = set()
    for part in value.replace(";", ",").split(","):
        if not part.strip():
            continue
        chat_id = validate_chat_id(part)
        if chat_id not in seen:
            chat_ids.append(chat_id)
            seen.add(chat_id)
    return chat_ids


def read_env_chat_ids(path: Path) -> list[str]:
    if not path.exists():
        return []

    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not ENV_LINE_PATTERN.match(line):
            continue
        value = line.split("=", 1)[1].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        return split_chat_ids(value)
    return []


def candidate_template() -> str:
    return (
        "# Her satıra yalnızca ChatID veya İsim=ChatID yazın. Örnekler:\n"
        "# 123456789\n"
        "# Ahmet=123456789\n"
        "# Arkadaş Grubu=-1001234567890\n"
        "# Boş satırlar ve # ile başlayan satırlar yok sayılır.\n"
    )


def ensure_candidate_file(path: Path, current_ids: list[str]) -> None:
    if not path.exists():
        path.write_text(candidate_template(), encoding="utf-8")

    text = path.read_text(encoding="utf-8-sig")
    has_candidate = any(
        line.strip() and not line.lstrip().startswith("#")
        for line in text.splitlines()
    )
    if has_candidate or not current_ids:
        return

    with path.open("a", encoding="utf-8", newline="") as handle:
        if text and not text.endswith(("\n", "\r")):
            handle.write("\n")
        handle.write("\n# .env içindeki mevcut ID'lerden otomatik oluşturuldu:\n")
        for index, chat_id in enumerate(current_ids, start=1):
            handle.write(f"Kişi {index}={chat_id}\n")


def read_candidates(path: Path) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    seen_ids: set[str] = set()
    errors: list[str] = []

    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            name, raw_id = (part.strip() for part in line.split("=", 1))
        else:
            name, raw_id = f"ID {line}", line
        if not name:
            errors.append(f"satır {line_number}: isim boş")
            continue
        try:
            chat_id = validate_chat_id(raw_id)
        except ValueError as exc:
            errors.append(f"satır {line_number}: {exc}")
            continue
        if chat_id in seen_ids:
            errors.append(f"satır {line_number}: {chat_id} daha önce tanımlanmış")
            continue

        candidates.append((name, chat_id))
        seen_ids.add(chat_id)

    if errors:
        raise ValueError("\n".join(errors))
    return candidates


def write_env_chat_ids(path: Path, selected_ids: list[str]) -> None:
    raw = path.read_bytes() if path.exists() else b""
    has_bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    newline = "\r\n" if "\r\n" in text else "\n"
    had_final_newline = text.endswith(("\n", "\r"))
    replacement = f"{ENV_KEY}={','.join(selected_ids)}"

    output: list[str] = []
    replaced = False
    for line in text.splitlines():
        if ENV_LINE_PATTERN.match(line):
            if not replaced:
                output.append(replacement)
                replaced = True
            continue
        output.append(line)

    if not replaced:
        output.append(replacement)

    updated = newline.join(output)
    if had_final_newline or not text:
        updated += newline

    encoded = updated.encode("utf-8")
    if has_bom:
        encoded = b"\xef\xbb\xbf" + encoded

    temporary = path.with_name(f"{path.name}.telegram-id-picker.tmp")
    try:
        temporary.write_bytes(encoded)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def print_menu(
    candidates: list[tuple[str, str]],
    selected: set[str],
    env_only_ids: set[str],
) -> None:
    print("\nTelegram alıcı seçimi")
    print("-" * 56)
    env_header_printed = False
    for index, (name, chat_id) in enumerate(candidates, start=1):
        if chat_id in env_only_ids and not env_header_printed:
            print("    — Yalnızca .env içinde olan aktif ID'ler —")
            env_header_printed = True
        marker = "x" if chat_id in selected else " "
        print(f"{index:>2}. [{marker}] {name} ({chat_id})")
    print("-" * 56)
    print("Numara(lar): seçimi aç/kapat   a: tümü   n: hiçbiri   s: kaydet   q: çık")


def confirm_exit_without_saving() -> bool:
    while True:
        try:
            answer = input(
                "Kaydetmeden çıkmak istediğine emin misin? [e/H]: "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nKaydetmeden çıkılıyor.")
            return True

        if answer in {"e", "evet", "y", "yes"}:
            return True
        if answer in {"", "h", "hayır", "hayir", "n", "no"}:
            return False
        print("Lütfen 'e' (evet) veya 'h' (hayır) girin.")


def run_picker(
    candidates: list[tuple[str, str]],
    current_ids: list[str],
    env_only_labels: dict[str, str] | None = None,
) -> bool:
    env_only_labels = env_only_labels or {}
    candidate_ids = {chat_id for _, chat_id in candidates}
    env_only_ids: set[str] = set()
    for index, chat_id in enumerate(current_ids, start=1):
        if chat_id not in candidate_ids:
            label = env_only_labels.get(chat_id, f"ENV'deki mevcut ID {index}")
            candidates.append((label, chat_id))
            candidate_ids.add(chat_id)
            env_only_ids.add(chat_id)

    initial_selected = set(current_ids)
    selected = set(initial_selected)
    while True:
        print_menu(candidates, selected, env_only_ids)
        try:
            command = input("Seçim: ").strip().lower()
        except KeyboardInterrupt:
            print()
            if selected == initial_selected or confirm_exit_without_saving():
                print("Değişiklik yapılmadı.")
                return False
            continue
        except EOFError:
            print("\nGirdi kapandı; değişiklik yapılmadı.")
            return False

        if command == "q":
            if selected == initial_selected or confirm_exit_without_saving():
                print("Değişiklik yapılmadı.")
                return False
            continue
        if command == "a":
            selected = set(candidate_ids)
            continue
        if command == "n":
            selected.clear()
            continue
        if command == "s":
            ordered_ids = [chat_id for _, chat_id in candidates if chat_id in selected]
            write_env_chat_ids(ENV_FILE, ordered_ids)
            print(f"Kaydedildi: {ENV_KEY}={','.join(ordered_ids)}")
            return True

        tokens = command.replace(",", " ").split()
        if not tokens or any(not token.isdigit() for token in tokens):
            print("Geçersiz seçim. Örnek: 1 3  veya  s")
            continue

        indexes = [int(token) for token in tokens]
        if any(index < 1 or index > len(candidates) for index in indexes):
            print(f"Seçim 1 ile {len(candidates)} arasında olmalıdır.")
            continue
        for index in indexes:
            chat_id = candidates[index - 1][1]
            if chat_id in selected:
                selected.remove(chat_id)
            else:
                selected.add(chat_id)


def main() -> int:
    try:
        current_ids = read_env_chat_ids(ENV_FILE)
        ensure_candidate_file(CANDIDATE_FILE, current_ids)
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        raw_count = raw_candidate_count(CANDIDATE_FILE)
        if raw_count:
            if token:
                print(f"{raw_count} ham ID için Telegram isimleri sorgulanıyor...")
                converted, lookup_errors = parse_candidate_file(
                    CANDIDATE_FILE, token
                )
                print(f"{converted}/{raw_count} ham ID otomatik isimlendirildi.")
                for error in lookup_errors:
                    print(f"Uyarı: {error}", file=sys.stderr)
            else:
                print(
                    "Uyarı: TELEGRAM_BOT_TOKEN olmadığı için ham ID'ler "
                    "isimlendirilemedi.",
                    file=sys.stderr,
                )
        candidates = read_candidates(CANDIDATE_FILE)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"Hata: {exc}", file=sys.stderr)
        return 1

    if not candidates and not current_ids:
        print(
            f"Aday bulunamadı. Önce {CANDIDATE_FILE.name} dosyasına "
            "İsim=ChatID satırları ekleyin.",
            file=sys.stderr,
        )
        return 1

    candidate_ids = {chat_id for _, chat_id in candidates}
    env_only_ids = [chat_id for chat_id in current_ids if chat_id not in candidate_ids]
    env_only_labels: dict[str, str] = {}
    if env_only_ids and token:
        print(
            f"Aday dosyasında olmayan {len(env_only_ids)} aktif ENV ID'sinin "
            "ismi sorgulanıyor..."
        )
        for chat_id in env_only_ids:
            try:
                chat = get_chat(token, chat_id)
                env_only_labels[chat_id] = label_for_chat(chat, chat_id)
            except TelegramLookupError as exc:
                print(f"Uyarı: {chat_id}: {exc}", file=sys.stderr)

    try:
        run_picker(candidates, current_ids, env_only_labels)
    except OSError as exc:
        print(f".env kaydedilemedi: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
