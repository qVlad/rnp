#!/usr/bin/env bash
# bump.sh — атомарный SemVer-bump для трёх файлов версий + /VERSION.
#
# Зачем: раньше bump делался руками в backend/pyproject.toml,
# frontend/package.json, extension/package.json — три файла, и при
# параллельных Claude-сессиях постоянно расходились (одна правит 0.6.0
# → 0.7.0, другая параллельно 0.6.0 → 0.6.1, при коммите последняя
# перезаписывает). Теперь:
#
#   1. /VERSION — единственный источник истины (видимый файл).
#   2. Этот скрипт читает /VERSION, бампает по SemVer, синхронно пишет
#      все 3 файла + сам /VERSION.
#   3. Безопасно запускается ТОЛЬКО под git-branch lock (см. scripts/lock.sh).
#
# Использование:
#   ./scripts/bump.sh patch   # 0.10.0 → 0.10.1
#   ./scripts/bump.sh minor   # 0.10.0 → 0.11.0
#   ./scripts/bump.sh major   # 0.10.0 → 1.0.0
#   ./scripts/bump.sh 0.12.3  # явная версия
#
# Печатает новую версию в stdout. Не коммитит — это делает remote.sh deploy
# или вызывающий скрипт.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION_FILE="${ROOT}/VERSION"

if [[ ! -f "${VERSION_FILE}" ]]; then
  echo "❌ ${VERSION_FILE} не найден" >&2
  exit 1
fi

current="$(cat "${VERSION_FILE}" | tr -d '[:space:]')"
if [[ ! "${current}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "❌ Текущая версия в /VERSION имеет некорректный формат: '${current}'" >&2
  exit 1
fi

bump_type="${1:-}"
if [[ -z "${bump_type}" ]]; then
  echo "Использование: $0 patch|minor|major|X.Y.Z" >&2
  exit 1
fi

IFS='.' read -r major minor patch <<< "${current}"

case "${bump_type}" in
  patch)
    new="${major}.${minor}.$((patch + 1))"
    ;;
  minor)
    new="${major}.$((minor + 1)).0"
    ;;
  major)
    new="$((major + 1)).0.0"
    ;;
  [0-9]*)
    if [[ ! "${bump_type}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
      echo "❌ Явная версия должна быть X.Y.Z (semver), а не '${bump_type}'" >&2
      exit 1
    fi
    new="${bump_type}"
    ;;
  *)
    echo "❌ Неизвестный bump_type '${bump_type}'. Допустимо: patch|minor|major|X.Y.Z" >&2
    exit 1
    ;;
esac

# Sanity check: новая версия > старой (для patch/minor/major это автоматом,
# для явной — проверяем что не делаем downgrade случайно).
if [[ "${bump_type}" =~ ^[0-9] ]]; then
  if [[ "$(printf '%s\n%s' "${current}" "${new}" | sort -V | head -1)" != "${current}" ]]; then
    echo "⚠ Предупреждение: явная версия ${new} <= текущей ${current} (downgrade)." >&2
    echo "  Если это намеренно (откат) — экспортируй BUMP_ALLOW_DOWNGRADE=1." >&2
    if [[ "${BUMP_ALLOW_DOWNGRADE:-0}" != "1" ]]; then
      exit 1
    fi
  fi
fi

echo "→ Bump ${current} → ${new}"

# 1. /VERSION
echo "${new}" > "${VERSION_FILE}"

# 2. backend/pyproject.toml (строка `version = "X.Y.Z"` в [project])
sed -i.bak -E "s/^(version = )\"[0-9]+\.[0-9]+\.[0-9]+\"/\\1\"${new}\"/" "${ROOT}/backend/pyproject.toml"
rm -f "${ROOT}/backend/pyproject.toml.bak"

# 3. frontend/package.json (поле "version")
# Используем python вместо sed/jq — json-форматирование стабильнее.
python3 - "${ROOT}/frontend/package.json" "${new}" <<'PY'
import json, sys
path, new = sys.argv[1], sys.argv[2]
with open(path) as f:
    data = json.load(f)
data["version"] = new
with open(path, "w") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.write("\n")
PY

# 4. extension/package.json
python3 - "${ROOT}/extension/package.json" "${new}" <<'PY'
import json, sys
path, new = sys.argv[1], sys.argv[2]
with open(path) as f:
    data = json.load(f)
data["version"] = new
with open(path, "w") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.write("\n")
PY

# Verify все 4 файла на одной версии — sanity check на случай sed/json-fail
actual_version="$(cat "${VERSION_FILE}" | tr -d '[:space:]')"
actual_backend="$(grep -E '^version = ' "${ROOT}/backend/pyproject.toml" | sed -E 's/version = "([^"]+)"/\1/')"
actual_frontend="$(python3 -c "import json; print(json.load(open('${ROOT}/frontend/package.json'))['version'])")"
actual_extension="$(python3 -c "import json; print(json.load(open('${ROOT}/extension/package.json'))['version'])")"

if [[ "${actual_version}" != "${new}" ]] || \
   [[ "${actual_backend}" != "${new}" ]] || \
   [[ "${actual_frontend}" != "${new}" ]] || \
   [[ "${actual_extension}" != "${new}" ]]; then
  echo "❌ Версии разъехались после bump'а:" >&2
  echo "   /VERSION:      ${actual_version}" >&2
  echo "   backend:       ${actual_backend}" >&2
  echo "   frontend:      ${actual_frontend}" >&2
  echo "   extension:     ${actual_extension}" >&2
  exit 1
fi

echo "✓ Все 4 файла на версии ${new}"
echo "${new}"
