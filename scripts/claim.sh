#!/usr/bin/env bash
# Claim mechanism (TASK-LEAD-024). См. agents/CLAIMS.md.
#
# Не mutex. Это координационный markdown — параллельная сессия проверяет
# agents/claims/<task-id>.claim.json перед взятием задачи. На уровне git
# конфликт всё ещё может случиться, но claim даёт явный сигнал «занято».

set -euo pipefail

CLAIMS_DIR="agents/claims"
mkdir -p "${CLAIMS_DIR}"

cmd_acquire() {
  local task_id="${1:?usage: claim.sh acquire <task-id> [notes]}"
  local notes="${2:-}"
  local file="${CLAIMS_DIR}/${task_id}.claim.json"

  if [[ -f "${file}" ]]; then
    local existing_agent
    existing_agent="$(grep -o '"agent": *"[^"]*"' "${file}" | head -1 | sed 's/.*"agent": *"//; s/"$//')"
    echo "ERROR: claim already exists for ${task_id}" >&2
    echo "  owner: ${existing_agent}" >&2
    echo "  file:  ${file}" >&2
    echo "  use './scripts/claim.sh status ${task_id}' for details" >&2
    echo "  use './scripts/claim.sh break-stale ${task_id}' to force-release (age >30 min)" >&2
    exit 2
  fi

  local agent_label="${CLAIM_AGENT:-${USER:-unknown}}"
  local started_at
  started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  cat > "${file}" <<EOF
{
  "task_id": "${task_id}",
  "agent": "${agent_label}",
  "started_at": "${started_at}",
  "expected_minutes": ${CLAIM_EXPECTED_MINUTES:-120},
  "notes": "${notes}"
}
EOF

  git add "${file}"
  git commit -q -m "claim(${task_id}): acquire — ${notes:-no notes}"
  git push -q || echo "warning: push failed (continue without remote sync)" >&2
  echo "✓ acquired ${task_id} (${file})"
}

cmd_release() {
  local task_id="${1:?usage: claim.sh release <task-id>}"
  local file="${CLAIMS_DIR}/${task_id}.claim.json"

  if [[ ! -f "${file}" ]]; then
    echo "no claim for ${task_id} (nothing to release)" >&2
    exit 0
  fi

  git rm -q "${file}"
  git commit -q -m "claim(${task_id}): release"
  git push -q || echo "warning: push failed" >&2
  echo "✓ released ${task_id}"
}

cmd_list() {
  if [[ -z "$(ls -A "${CLAIMS_DIR}" 2>/dev/null || true)" ]]; then
    echo "no active claims"
    return 0
  fi
  echo "TASK_ID                AGENT                                          AGE"
  for f in "${CLAIMS_DIR}"/*.claim.json; do
    [[ -f "${f}" ]] || continue
    local task_id agent started age_min
    task_id="$(basename "${f}" .claim.json)"
    agent="$(grep -o '"agent": *"[^"]*"' "${f}" | head -1 | sed 's/.*"agent": *"//; s/"$//')"
    started="$(grep -o '"started_at": *"[^"]*"' "${f}" | head -1 | sed 's/.*"started_at": *"//; s/"$//')"
    age_min="$(python3 -c "from datetime import datetime, timezone; d=datetime.fromisoformat('${started}'.replace('Z','+00:00')); print(int((datetime.now(timezone.utc) - d).total_seconds() // 60))" 2>/dev/null || echo "?")"
    printf "%-22s %-46s %s min\n" "${task_id}" "${agent}" "${age_min}"
  done
}

cmd_status() {
  local task_id="${1:?usage: claim.sh status <task-id>}"
  local file="${CLAIMS_DIR}/${task_id}.claim.json"
  if [[ ! -f "${file}" ]]; then
    echo "no claim"
    exit 0
  fi
  cat "${file}"
}

cmd_break_stale() {
  local task_id="${1:-}"
  if [[ -n "${task_id}" ]]; then
    files=("${CLAIMS_DIR}/${task_id}.claim.json")
  else
    files=("${CLAIMS_DIR}"/*.claim.json)
  fi
  for f in "${files[@]}"; do
    [[ -f "${f}" ]] || continue
    local started age_min expected_min budget_min
    started="$(grep -o '"started_at": *"[^"]*"' "${f}" | head -1 | sed 's/.*"started_at": *"//; s/"$//')"
    expected_min="$(grep -o '"expected_minutes": *[0-9]*' "${f}" | head -1 | awk '{print $NF}')"
    expected_min="${expected_min:-120}"
    budget_min=$((expected_min + 60))  # buffer 60 min
    age_min="$(python3 -c "from datetime import datetime, timezone; d=datetime.fromisoformat('${started}'.replace('Z','+00:00')); print(int((datetime.now(timezone.utc) - d).total_seconds() // 60))" 2>/dev/null || echo "0")"
    if (( age_min > budget_min )); then
      echo "→ expiring $(basename "${f}") (age=${age_min}min > budget=${budget_min}min)"
      git rm -q "${f}"
    fi
  done
  if ! git diff --staged --quiet 2>/dev/null; then
    git commit -q -m "claim: expire stale claims"
    git push -q || echo "warning: push failed" >&2
    echo "✓ stale claims expired"
  else
    echo "no stale claims to expire"
  fi
}

case "${1:-}" in
  acquire)     shift; cmd_acquire "$@" ;;
  release)     shift; cmd_release "$@" ;;
  list)        cmd_list ;;
  status)      shift; cmd_status "$@" ;;
  break-stale) shift; cmd_break_stale "$@" ;;
  *)
    cat <<USAGE >&2
Usage: $0 <command> [args]

Commands:
  acquire <task-id> [notes]   создать claim
  release <task-id>           удалить claim
  list                        показать все активные claim'ы
  status <task-id>            показать конкретный claim
  break-stale [task-id]       удалить просроченные (или конкретный)

См. agents/CLAIMS.md.
USAGE
    exit 1
    ;;
esac
