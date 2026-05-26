#!/usr/bin/env python3
"""TASK-LEAD-121 — auto-close статусов задач/багов по commit-сообщениям.

Что делает:
    1. Берёт git-range (от последнего коммита, который менял `/VERSION`, до HEAD —
       т.е. все коммиты текущего релиза). Можно override через `--since`.
    2. Greps commit messages на pattern `(TASK-LEAD|BUG-DEV|BUG-UI)-\\d+`.
    3. Для каждого найденного ID находит запись в соответствующем .md:
       - `TASK-LEAD-NNN` → `agents/tasks-lead.md`
       - `BUG-DEV-NNN`   → `agents/bugs-developer.md`
       - `BUG-UI-NNN`    → `agents/bugs-design-engineer.md`
    4. Если статус «Открыта» (или «Открыт» для багов) — спрашивает и обновляет
       на «Выполнено — YYYY-MM-DD (auto-close)» (или «Исправлено — …»).
    5. Если статус уже не открыт — пропускает с notice.

Use cases:
    # После bump'а (interactive):
    ./scripts/close-tasks-from-commits.py

    # Авто-режим (без вопросов):
    ./scripts/close-tasks-from-commits.py --auto

    # Dry-run — показать что бы изменилось:
    ./scripts/close-tasks-from-commits.py --dry-run

    # Custom range:
    ./scripts/close-tasks-from-commits.py --since v0.38.0..HEAD

Зачем (round-14 синтез — 3-й раунд подряд):
    У нас регулярно остаются «Открыта» статусы на задачах, которые уже
    закоммичены и в проде. Reviewer'ы их видят как stale в каждом post-feature
    review и тратят время на ручной cleanup. Этот скрипт закрывает gap.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASKS_LEAD = ROOT / "agents" / "tasks-lead.md"
BUGS_DEV = ROOT / "agents" / "bugs-developer.md"
BUGS_UI = ROOT / "agents" / "bugs-design-engineer.md"

ID_PATTERN = re.compile(r"\b(TASK-LEAD|BUG-DEV|BUG-UI|UNIT-PLAN)-(\d+)\b")


def _run(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, cwd=ROOT, text=True).strip()


def _resolve_range(since: str | None) -> str:
    if since:
        return since
    # Берём последний commit где /VERSION менялся — это маркер предыдущего bump'а
    try:
        prev_commit = _run([
            "git", "log", "-n", "2", "--format=%H", "--", "VERSION",
        ]).splitlines()
        if len(prev_commit) >= 2:
            return f"{prev_commit[1]}..HEAD"
    except subprocess.CalledProcessError:
        pass
    # Fallback — последние 20 коммитов
    return "HEAD~20..HEAD"


def _collect_ids(rng: str) -> dict[str, list[str]]:
    """Returns {full_id: [commit_short_sha, ...]} в порядке появления."""
    log = _run(["git", "log", "--format=%h %s", rng])
    found: dict[str, list[str]] = {}
    for line in log.splitlines():
        if not line.strip():
            continue
        sha, _, msg = line.partition(" ")
        for prefix, num in ID_PATTERN.findall(msg):
            full_id = f"{prefix}-{num}"
            found.setdefault(full_id, []).append(sha)
    return found


def _file_for(full_id: str) -> Path:
    if full_id.startswith("TASK-LEAD-") or full_id.startswith("UNIT-PLAN-"):
        return TASKS_LEAD
    if full_id.startswith("BUG-DEV-"):
        return BUGS_DEV
    if full_id.startswith("BUG-UI-"):
        return BUGS_UI
    raise ValueError(f"unknown id prefix: {full_id}")


def _resolved_label(full_id: str, today: str, reason: str = "auto-close") -> str:
    """Pattern для status-замены."""
    if full_id.startswith("BUG-"):
        return f"Исправлено — {today} ({reason})"
    return f"Выполнено — {today} ({reason})"


def _try_close(full_id: str, commits: list[str], today: str,
               *, auto: bool, dry_run: bool, reason: str = "auto-close") -> str:
    """Returns: 'closed' | 'skipped' | 'already-closed' | 'not-found'."""
    path = _file_for(full_id)
    if not path.exists():
        return "not-found"

    text = path.read_text(encoding="utf-8")
    # Найти секцию задачи: `### TASK-LEAD-NNN:` или `## BUG-NNN:` (с любым
    # заголовком после двоеточия), от неё до следующего `### ` или `## ` или
    # `---`. Внутри ищем `- **Статус:**` строку.
    header_re = re.compile(
        rf"^(?:#+|\#{{2,3}})\s+{re.escape(full_id)}(?:[:\s].*)?$",
        re.MULTILINE,
    )
    m = header_re.search(text)
    if not m:
        return "not-found"

    # Граница секции — следующий header того же уровня или больше, или `---`
    end = len(text)
    for next_m in re.finditer(r"^(?:#+|---)\s*", text[m.end():], re.MULTILINE):
        end = m.end() + next_m.start()
        break

    section = text[m.start():end]

    # Найти строку статуса. Обычно "- **Статус:** Открыта" или "Открыт".
    status_re = re.compile(
        r"^(\s*-\s*\*\*Статус:\*\*\s*)(.+?)\s*$",
        re.MULTILINE,
    )
    status_m = status_re.search(section)
    if not status_m:
        return "not-found"

    current_status = status_m.group(2).strip()
    is_open = current_status.lower() in {"открыта", "открыт"}
    if not is_open:
        return "already-closed"

    new_status = _resolved_label(full_id, today, reason)
    commits_str = ", ".join(commits[:3])
    if len(commits) > 3:
        commits_str += f" + {len(commits) - 3} more"

    if not auto:
        print(f"\n{full_id}: status = '{current_status}'")
        print(f"  commit(s): {commits_str}")
        print(f"  → close as '{new_status}'? [y/N] ", end="", flush=True)
        ans = input().strip().lower()
        if ans != "y":
            return "skipped"

    if dry_run:
        print(f"  [dry-run] would replace '{current_status}' → '{new_status}'")
        return "closed"

    new_section = (
        section[: status_m.start(2)] + new_status + section[status_m.end(2):]
    )
    new_text = text[: m.start()] + new_section + text[end:]
    path.write_text(new_text, encoding="utf-8")
    return "closed"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", default=None,
                    help="git-range (default: from previous /VERSION commit to HEAD)")
    ap.add_argument("--ids", default=None,
                    help="Comma-separated list of IDs to close (bypasses git-log scan). "
                         "Example: --ids UNIT-PLAN-001,UNIT-PLAN-002. Useful for stale-cleanup "
                         "когда задачи реализованы, но ID не попали в commit message.")
    ap.add_argument("--reason", default="auto-close",
                    help="Suffix в новом статусе. Default: 'auto-close'. "
                         "Для stale cleanup: --reason 'stale-cleanup'.")
    ap.add_argument("--auto", action="store_true",
                    help="Non-interactive — close all without prompting")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show what would change, don't write files")
    args = ap.parse_args()

    if args.ids:
        explicit_ids = [s.strip() for s in args.ids.split(",") if s.strip()]
        ids = {full_id: ["(explicit)"] for full_id in explicit_ids}
        print(f"→ Using explicit IDs: {', '.join(sorted(ids.keys()))}")
    else:
        rng = _resolve_range(args.since)
        print(f"→ Scanning commit range: {rng}")
        ids = _collect_ids(rng)
        if not ids:
            print("✓ No TASK-LEAD/BUG-DEV/BUG-UI/UNIT-PLAN references in range — nothing to close.")
            return 0

        print(f"→ Found {len(ids)} unique ID(s): {', '.join(sorted(ids.keys()))}")
    today = date.today().isoformat()

    stats: dict[str, int] = {"closed": 0, "skipped": 0, "already-closed": 0, "not-found": 0}
    for full_id, commits in sorted(ids.items()):
        result = _try_close(full_id, commits, today,
                            auto=args.auto, dry_run=args.dry_run, reason=args.reason)
        stats[result] += 1
        prefix = {
            "closed": "✓",
            "skipped": "○",
            "already-closed": "✓",
            "not-found": "?",
        }[result]
        if args.auto or result != "skipped":
            print(f"  {prefix} {full_id}: {result}")

    print(
        f"\nDone: {stats['closed']} closed, {stats['skipped']} skipped, "
        f"{stats['already-closed']} already-closed, {stats['not-found']} not-found."
    )
    if args.dry_run:
        print("(dry-run mode — no files changed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
