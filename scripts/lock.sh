#!/usr/bin/env bash
# lock.sh — атомарный release/deploy mutex через git-branch.
#
# ПРОБЛЕМА: DEPLOY_LOCK.md как markdown-mutex не работает. Два Claude'а
# одновременно читают «🟢 Свободно», оба ставят свой замок, последний
# побеждает. Stale-locks (сессия упала с замком) висят навсегда.
#
# РЕШЕНИЕ: git-branch как mutex. `release-lock` — служебная ветка с одним
# коммитом, содержащим owner+timestamp в commit message. `git push origin
# release-lock` атомарен на стороне github — у одного push'нулось, у
# другого `! [rejected]`. TTL 30 минут — после этого `break-stale` любой
# может перебить (force-push) с записью в commit message.
#
# Использование:
#   ./scripts/lock.sh acquire <owner> <reason>
#       Захватить замок. Печатает COMMIT_HASH в stdout, exit 0.
#       Если занят — exit 1 + печатает кем/когда/чем.
#
#   ./scripts/lock.sh release <commit-hash>
#       Снять замок. Проверяет что текущий замок имеет тот же hash
#       (защита от случайного release чужого замка). exit 0.
#
#   ./scripts/lock.sh status
#       Печатает текущее состояние замка (🟢 / 🔴) в человекочитаемом
#       формате. exit 0.
#
#   ./scripts/lock.sh break-stale
#       Если текущий замок старше TTL_MIN — force-удаляет (любой). exit 0.
#       Иначе exit 1 с указанием на актуальный замок.
#
# Тонкости:
# - `release-lock` НЕ ветка для merge, просто служебная (как `gh-pages`).
#   Никогда не сливается в main.
# - acquire создаёт пустой commit в detached HEAD'е, потом пушит как
#   `refs/heads/release-lock`. Force-with-lease не используется при первом
#   acquire — push без --force должен фейлиться если ветка уже существует.
#
# Для emergency override (например когда github offline) — оператор может
# вручную закоммитить в release-lock с force-push, lock.sh status это
# подхватит на следующем acquire.
set -euo pipefail

LOCK_BRANCH="release-lock"
TTL_MIN="${LOCK_TTL_MIN:-30}"
REMOTE="${LOCK_REMOTE:-origin}"

cmd="${1:-status}"

# --- helpers ---

# Получить последний commit на release-lock (с remote). Печатает hash или пусто.
# ls-remote напрямую опрашивает remote — не зависит от локального fetch state
# и не плодит stale-refs в refs/remotes/.
remote_lock_head() {
  local out
  out="$(git ls-remote "${REMOTE}" "refs/heads/${LOCK_BRANCH}" 2>/dev/null || true)"
  # ls-remote формат: "<hash>\t<ref>"
  if [[ -z "${out}" ]]; then
    echo ""
    return
  fi
  echo "${out}" | awk '{print $1}'
}

# Подтягивает commit object замка в локальный repo (если ещё не в .git).
# Нужно потому что `git log` ниже требует наличия commit'а в локальном
# object store — ls-remote даёт только hash.
ensure_local_commit() {
  local hash="$1"
  if git cat-file -e "${hash}" 2>/dev/null; then
    return 0
  fi
  # fetch конкретного hash'а; refspec пишет в FETCH_HEAD, без создания ветки.
  git fetch "${REMOTE}" "${hash}" 2>/dev/null || \
    git fetch "${REMOTE}" "refs/heads/${LOCK_BRANCH}:refs/remotes/${REMOTE}/${LOCK_BRANCH}" 2>/dev/null || true
}

# Возраст замка в минутах (по commit timestamp).
lock_age_min() {
  local hash="$1"
  ensure_local_commit "${hash}"
  local committed_at
  committed_at="$(git log -1 --format=%ct "${hash}" 2>/dev/null || echo 0)"
  if [[ -z "${committed_at}" || "${committed_at}" == "0" ]]; then
    echo "0"
    return
  fi
  local now
  now="$(date +%s)"
  echo $(( (now - committed_at) / 60 ))
}

# Парсит owner/reason из commit message замка.
lock_meta() {
  local hash="$1"
  ensure_local_commit "${hash}"
  git log -1 --format=%B "${hash}" 2>/dev/null | head -5
}

# --- commands ---

case "${cmd}" in
  status)
    head="$(remote_lock_head)"
    if [[ -z "${head}" ]]; then
      echo "🟢 Замок свободен (нет ветки ${LOCK_BRANCH} на ${REMOTE})"
      exit 0
    fi
    age="$(lock_age_min "${head}")"
    echo "🔴 Замок занят (commit=${head:0:7}, age=${age}мин)"
    echo "---"
    lock_meta "${head}"
    if (( age >= TTL_MIN )); then
      echo "---"
      echo "⏱ Замок старше TTL=${TTL_MIN}мин — можно перебить через 'lock.sh break-stale'"
    fi
    exit 0
    ;;

  acquire)
    owner="${2:-}"
    reason="${3:-}"
    if [[ -z "${owner}" || -z "${reason}" ]]; then
      echo "Использование: $0 acquire <owner> <reason>" >&2
      exit 2
    fi
    head="$(remote_lock_head)"
    if [[ -n "${head}" ]]; then
      age="$(lock_age_min "${head}")"
      if (( age < TTL_MIN )); then
        echo "❌ Замок занят (${age}мин < TTL ${TTL_MIN}мин). Подробности:" >&2
        lock_meta "${head}" >&2
        exit 1
      fi
      # Stale — для acquire не перебиваем молча, требуем явный break-stale
      # (защита от двух одновременных acquire-через-stale; первый break,
      # второй увидит свежий замок). Если оператор хочет — пусть запускает
      # break-stale явно.
      echo "❌ Замок stale (${age}мин ≥ TTL ${TTL_MIN}мин). Сначала запусти:" >&2
      echo "     ./scripts/lock.sh break-stale" >&2
      lock_meta "${head}" >&2
      exit 1
    fi
    # Создаём empty commit в detached HEAD и пушим как новую ветку.
    # `--no-thin` чтобы push не использовал delta-compression к main
    # (release-lock не имеет общих предков с main).
    parent_tree="$(git mktree </dev/null)"
    new_commit="$(git commit-tree "${parent_tree}" -m "lock acquired

Owner: ${owner}
Reason: ${reason}
Acquired-At: $(date -u +%Y-%m-%dT%H:%M:%SZ)
Acquired-By-Host: $(hostname)
")"
    # Push с refspec — github отвергнет если ${LOCK_BRANCH} уже существует.
    # stderr скрываем чтобы stdout содержал ТОЛЬКО hash (для capture'а
    # вызывающим: HASH=$(./lock.sh acquire ...)).
    if ! git push --no-thin "${REMOTE}" "${new_commit}:refs/heads/${LOCK_BRANCH}" >/dev/null 2>&1; then
      # Race: кто-то успел между нашими remote_lock_head и push'ем.
      echo "❌ Race condition: кто-то захватил замок параллельно. Повтори через минуту." >&2
      exit 1
    fi
    echo "${new_commit}"
    ;;

  release)
    expected_hash="${2:-}"
    if [[ -z "${expected_hash}" ]]; then
      echo "Использование: $0 release <commit-hash>" >&2
      exit 2
    fi
    head="$(remote_lock_head)"
    if [[ -z "${head}" ]]; then
      echo "⚠ Замок уже снят — ничего не делаю" >&2
      exit 0
    fi
    if [[ "${head}" != "${expected_hash}" ]]; then
      echo "❌ Текущий замок (${head:0:7}) не совпадает с ожидаемым (${expected_hash:0:7})." >&2
      echo "  Кто-то перебил твой замок. Не снимаю чужой. Дополнительно — посмотри 'lock.sh status'." >&2
      exit 1
    fi
    # Удаляем ветку на remote.
    if git push "${REMOTE}" --delete "${LOCK_BRANCH}" >/dev/null 2>&1; then
      echo "🟢 Замок снят"
    else
      echo "❌ git push --delete упал" >&2
      exit 1
    fi
    ;;

  break-stale)
    head="$(remote_lock_head)"
    if [[ -z "${head}" ]]; then
      echo "🟢 Замок уже свободен"
      exit 0
    fi
    age="$(lock_age_min "${head}")"
    if (( age < TTL_MIN )); then
      echo "❌ Замок свежий (${age}мин < TTL ${TTL_MIN}мин). break-stale запрещён." >&2
      lock_meta "${head}" >&2
      exit 1
    fi
    echo "⏱ Замок stale (${age}мин ≥ TTL ${TTL_MIN}мин). Удаляю."
    lock_meta "${head}"
    git push "${REMOTE}" --delete "${LOCK_BRANCH}" >/dev/null 2>&1
    echo "🟢 Замок снят"
    ;;

  *)
    echo "Неизвестная команда: ${cmd}" >&2
    echo "Доступно: status | acquire <owner> <reason> | release <hash> | break-stale" >&2
    exit 2
    ;;
esac
