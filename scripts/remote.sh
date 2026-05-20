#!/usr/bin/env bash
# remote.sh — управление боевым сервером РНП с локальной машины.
# Один скрипт на всё: setup, deploy (с backup), backup, restore, status, logs, shell.
#
# ОБЯЗАТЕЛЬНОЕ ПРАВИЛО: команда `deploy` ВСЕГДА делает pg_dump перед накаткой
# изменений (если postgres запущен). Бэкап лежит на сервере в
# /opt/rnp/backups/rnp-<timestamp>-pre-deploy.sql.gz и хранится бессрочно.
# Не пропускай этот шаг даже если правки кажутся «лёгкими» — миграции бд могут
# незаметно сломать данные, и без бэкапа откат невозможен.
#
# Запуск из корня репо (там, где docker-compose.yml):
#   ./scripts/remote.sh setup    # один раз — поставить docker, mkdir
#   ./scripts/remote.sh deploy   # rsync + backup + up -d --build
#   ./scripts/remote.sh backup [label]
#   ./scripts/remote.sh restore <file>
#   ./scripts/remote.sh status
#   ./scripts/remote.sh logs [service]
#   ./scripts/remote.sh shell [service]    # default: backend
#   ./scripts/remote.sh help

set -euo pipefail

SERVER="${SERVER:-vlad@192.168.31.61}"
REMOTE_DIR="${REMOTE_DIR:-/opt/rnp}"
PUBLIC_IP="${PUBLIC_IP:-94.198.130.185}"
PORT="${PORT:-4098}"

ssh_cmd() {
  ssh -o StrictHostKeyChecking=accept-new "${SERVER}" "$@"
}

ensure_ssh_key() {
  # Проверяет, что ssh без пароля работает; если нет — заливает наш pub-key
  # на сервер через ssh-copy-id (попросит пароль 1 раз).
  if ssh -o BatchMode=yes -o ConnectTimeout=5 "${SERVER}" true 2>/dev/null; then
    return 0
  fi
  echo "→ Беспарольный ssh не настроен. Сейчас зальём ключ через ssh-copy-id"
  echo "  (нужно будет ввести серверный пароль один раз)."
  if [ ! -f ~/.ssh/id_ed25519 ] && [ ! -f ~/.ssh/id_rsa ]; then
    echo "  Генерирую ed25519 ключ в ~/.ssh/id_ed25519…"
    ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N ""
  fi
  ssh-copy-id -o StrictHostKeyChecking=accept-new "${SERVER}"
  echo "✓ Ключ установлен."
}

remote_backup() {
  local label="${1:-manual}"
  local stamp; stamp="$(date +%Y%m%d-%H%M%S)"
  local fname="rnp-${stamp}-${label}.sql.gz"
  echo "→ Бэкап БД на сервере: backups/${fname}"
  ssh_cmd "set -e
    mkdir -p ${REMOTE_DIR}/backups
    cd ${REMOTE_DIR}
    docker compose exec -T postgres pg_dump -U app rnp | gzip > backups/${fname}
    ls -lh backups/${fname}
  "
}

cmd_setup() {
  ensure_ssh_key
  echo "→ Установка docker + подготовка ${REMOTE_DIR} на ${SERVER}"
  echo "  (sudo на сервере попросит пароль один раз — вводи интерактивно)"
  # `-t` allocates a pseudo-TTY чтобы sudo мог запросить пароль. Без этого
  # sudo падает с 'a terminal is required to read the password'.
  ssh -t -o StrictHostKeyChecking=accept-new "${SERVER}" "set -e
    export LC_ALL=C  # подавляет warning'и про локаль
    if ! command -v docker >/dev/null 2>&1; then
      echo '  apt-get install docker…'
      sudo apt-get update -qq
      sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
        docker.io docker-compose-plugin git rsync
    fi
    # Добавляем юзера в группу docker (если ещё нет).
    if ! id -nG | grep -qw docker; then
      sudo usermod -aG docker \$(whoami)
      NEED_RELOGIN=1
    fi
    # Каталог под сервис.
    if [ ! -d ${REMOTE_DIR} ]; then
      sudo mkdir -p ${REMOTE_DIR}/backups
      sudo chown -R \$(whoami):\$(whoami) ${REMOTE_DIR}
    fi
    docker --version || true
    if [ \"\${NEED_RELOGIN:-0}\" = \"1\" ]; then
      echo
      echo '  ⚠️  Группа docker применяется только при новом ssh-сеансе.'
      echo '      Это нормально — следующая команда (deploy) создаст новое ssh-подключение.'
    fi
  "
  echo
  echo "✓ Сервер готов."
  echo "  Дальше: ./scripts/remote.sh deploy   (первый раз создаст .env-шаблон)"
}

cmd_deploy() {
  ensure_ssh_key

  if [ ! -f docker-compose.yml ]; then
    echo "ERROR: запускай из корня репо (где docker-compose.yml)" >&2
    exit 1
  fi

  # 0. Если на сервере нет .env — накатываем шаблон и просим заполнить.
  if ! ssh_cmd "test -f ${REMOTE_DIR}/.env" 2>/dev/null; then
    echo "→ .env на сервере не найден. Создаю из шаблона."
    rsync -avz .env.production.example "${SERVER}:${REMOTE_DIR}/.env"
    echo
    echo "⚠️  Заполни .env на сервере перед продолжением:"
    echo "      ssh ${SERVER}"
    echo "      nano ${REMOTE_DIR}/.env"
    echo
    echo "  Обязательные поля: WB_TOKEN, JWT_SECRET_KEY"
    echo "  После — запусти './scripts/remote.sh deploy' ещё раз."
    exit 0
  fi

  # 1. ОБЯЗАТЕЛЬНЫЙ бэкап перед обновлением, если postgres уже запущен.
  echo "→ Проверяю запущенные контейнеры для pre-deploy бэкапа…"
  if ssh_cmd "cd ${REMOTE_DIR} && docker compose ps --status running --services 2>/dev/null | grep -qx postgres" 2>/dev/null; then
    remote_backup "pre-deploy"
  else
    echo "  Postgres ещё не запущен (первый деплой) — бэкап не требуется."
  fi

  # 1.7. Pre-flight: активные celery-таски.
  # Деплой пересоздаёт worker-контейнеры → SIGTERM → warm shutdown
  # (до stop_grace_period=1800s = 30 мин). Если задача не успеет, она
  # вернётся в очередь благодаря acks_late+reject_on_worker_lost, но
  # пользователь должен видеть, что задержит деплой.
  # FORCE=1 / FAST=1 пропускают ожидание; WAIT_MAX_SEC ограничивает таймаут.
  if [ "${FORCE:-0}" != "1" ] && [ "${FAST:-0}" != "1" ]; then
    echo "→ Проверяю активные celery-таски…"
    local active_count
    active_count="$(ssh_cmd "cd ${REMOTE_DIR} && \
      docker compose ps --status running --services 2>/dev/null | grep -q '^worker' && \
      docker compose exec -T worker-default celery -A app.sync.celery_app inspect active --timeout=3 2>/dev/null \
        | grep -cE '^\s*\* ' || true" 2>/dev/null || echo 0)"
    active_count="${active_count//[!0-9]/}"
    active_count="${active_count:-0}"
    if [ "${active_count}" -gt 0 ]; then
      echo
      echo "  ⚠️  Сейчас выполняется активных задач: ${active_count}"
      ssh_cmd "cd ${REMOTE_DIR} && docker compose exec -T worker-default \
        celery -A app.sync.celery_app inspect active --timeout=3 2>/dev/null \
        | grep -E 'name|args|time_start' | head -20" 2>/dev/null || true
      echo
      echo "  Варианты:"
      echo "    [w]ait    — подождать завершения (опрос каждые 30 сек, max ${WAIT_MAX_SEC:-1800} сек)"
      echo "    [f]orce   — деплоить сейчас (worker'ы будут warm-shutdown до 30 мин,"
      echo "                незавершённые задачи вернутся в очередь автоматически)"
      echo "    [c]ancel  — отменить деплой"
      read -r -p "  Выбор [w/f/c, default w]: " choice
      choice="${choice:-w}"
      case "${choice}" in
        w|W)
          local waited=0 max="${WAIT_MAX_SEC:-1800}"
          while [ "${waited}" -lt "${max}" ]; do
            sleep 30
            waited=$((waited + 30))
            active_count="$(ssh_cmd "cd ${REMOTE_DIR} && \
              docker compose exec -T worker-default celery -A app.sync.celery_app inspect active --timeout=3 2>/dev/null \
                | grep -cE '^\s*\* ' || true" 2>/dev/null || echo 0)"
            active_count="${active_count//[!0-9]/}"
            active_count="${active_count:-0}"
            echo "  [${waited}s/${max}s] активных задач: ${active_count}"
            if [ "${active_count}" -eq 0 ]; then
              echo "  ✓ Все задачи завершены."
              break
            fi
          done
          if [ "${active_count}" -gt 0 ]; then
            echo "  ⚠️  Таймаут (${max} сек) — задачи всё ещё идут. Продолжаю деплой;"
            echo "      незавершённые задачи вернутся в очередь."
          fi
          ;;
        f|F)
          echo "  → Деплой с force. Незавершённые задачи вернутся в очередь."
          ;;
        c|C)
          echo "  Деплой отменён."
          exit 0
          ;;
        *)
          echo "  Неизвестный выбор '${choice}' — деплой отменён."
          exit 1
          ;;
      esac
    else
      echo "  Активных задач нет."
    fi
  else
    echo "→ FORCE=1: пропускаю pre-flight проверку задач."
  fi

  # 1.5 Версия: git short hash + ISO build time → в .env на сервере.
  # Backend exposes их через /api/version, UI показывает в шапке.
  local version build_time
  version="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
  if ! git diff --quiet 2>/dev/null || ! git diff --cached --quiet 2>/dev/null; then
    version="${version}-dirty"
  fi
  build_time="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "→ Версия: ${version} (built ${build_time})"
  # Обновляем 2 строки в /opt/rnp/.env (создаём если нет).
  ssh_cmd "cd ${REMOTE_DIR} && touch .env && \
    grep -q '^APP_VERSION=' .env && sed -i 's|^APP_VERSION=.*|APP_VERSION=${version}|' .env || echo 'APP_VERSION=${version}' >> .env; \
    grep -q '^BUILD_TIME=' .env  && sed -i 's|^BUILD_TIME=.*|BUILD_TIME=${build_time}|' .env  || echo 'BUILD_TIME=${build_time}' >> .env"

  # 2. rsync кода.
  echo "→ rsync кода → ${SERVER}:${REMOTE_DIR}/"
  rsync -avz --delete \
    --exclude '.git' \
    --exclude '__pycache__' \
    --exclude 'node_modules' \
    --exclude 'frontend/dist' \
    --exclude '.claude' \
    --exclude '.env' \
    --exclude 'pgdata' \
    --exclude 'backups' \
    --exclude '.DS_Store' \
    --exclude '*.pyc' \
    ./ "${SERVER}:${REMOTE_DIR}/"

  # 3. up -d --build (миграции прокатятся внутри backend).
  # FAST=1 → не ждём warm shutdown воркеров (stop_grace_period=1800s),
  # шлём SIGKILL через 10 сек. Активные таски вернутся в очередь благодаря
  # task_acks_late + task_reject_on_worker_lost, новый worker их подхватит.
  # Без FAST=1 — стандартный graceful shutdown до 30 мин.
  if [ "${FAST:-0}" = "1" ]; then
    echo "→ FAST=1: предварительный stop --timeout=10 для воркеров (SIGKILL через 10s)"
    ssh_cmd "cd ${REMOTE_DIR} && docker compose stop --timeout=10 worker-stats worker-advert worker-default beat || true"
  fi
  echo "→ docker compose up -d --build…"
  ssh_cmd "cd ${REMOTE_DIR} && docker compose up -d --build"

  echo
  echo "→ Статус:"
  ssh_cmd "cd ${REMOTE_DIR} && docker compose ps --format 'table {{.Service}}\t{{.Status}}'"

  echo
  echo "✓ Деплой завершён."
  echo "  Локально: http://192.168.31.61:${PORT}/"
  echo "  Снаружи:  http://${PUBLIC_IP}:${PORT}/  (порт ${PORT} проброшен)"
}

cmd_backup() {
  ensure_ssh_key
  remote_backup "${1:-manual}"
}

cmd_restore() {
  ensure_ssh_key
  local file="${1:-}"
  if [ -z "${file}" ]; then
    echo "Usage: $0 restore <filename>"
    echo "Доступные бэкапы:"
    ssh_cmd "ls -1tr ${REMOTE_DIR}/backups/ 2>/dev/null || echo '(нет)'"
    exit 1
  fi
  echo "Восстановит БД из ${file}. Текущие данные будут ПЕРЕЗАПИСАНЫ."
  read -r -p "Введи 'yes' для подтверждения: " confirm
  [[ "${confirm}" == "yes" ]] || { echo "Отмена."; exit 0; }
  # Сначала свежий бэкап — на случай если restore окажется неверным.
  remote_backup "pre-restore"
  ssh_cmd "set -e
    cd ${REMOTE_DIR}
    gunzip < backups/${file} | docker compose exec -T postgres psql -U app -d rnp
  "
  echo "✓ Восстановлено из ${file}"
}

cmd_status() {
  ssh_cmd "cd ${REMOTE_DIR} && docker compose ps --format 'table {{.Service}}\t{{.Status}}'"
}

cmd_push_env() {
  # Заменяет .env на сервере свежим ASCII-шаблоном, сохраняя ранее
  # заполненные секреты (WB_TOKEN, JWT_SECRET_KEY, TG_BOT_TOKEN).
  # Полезно если .env на сервере был испорчен (некорректная кодировка,
  # удалённые ключи и т.п.).
  ensure_ssh_key
  if [ ! -f .env.production.example ]; then
    echo "ERROR: .env.production.example не найден локально" >&2
    exit 1
  fi

  echo "→ Скачиваю текущий .env с сервера для извлечения секретов…"
  local tmp_old; tmp_old="$(mktemp)"
  if ssh_cmd "test -f ${REMOTE_DIR}/.env" 2>/dev/null; then
    rsync -az "${SERVER}:${REMOTE_DIR}/.env" "${tmp_old}" 2>/dev/null || true
  fi

  echo "→ Делаю backup старого .env на сервере…"
  ssh_cmd "test -f ${REMOTE_DIR}/.env && cp ${REMOTE_DIR}/.env ${REMOTE_DIR}/.env.bak.\$(date +%Y%m%d-%H%M%S) || true"

  # Извлекаем сохранённые значения из старого .env (если он был).
  local wb_token jwt_key tg_token
  if [ -s "${tmp_old}" ]; then
    # iconv в UTF-8 на всякий случай — переводит из любой кодировки в UTF-8,
    # битые байты заменяет.
    iconv -f UTF-8 -t UTF-8//IGNORE "${tmp_old}" -o "${tmp_old}.clean" 2>/dev/null \
      || cp "${tmp_old}" "${tmp_old}.clean"
    wb_token="$(grep -E '^WB_TOKEN=' "${tmp_old}.clean" | head -1 | cut -d'=' -f2- || true)"
    jwt_key="$(grep -E '^JWT_SECRET_KEY=' "${tmp_old}.clean" | head -1 | cut -d'=' -f2- || true)"
    tg_token="$(grep -E '^TG_BOT_TOKEN=' "${tmp_old}.clean" | head -1 | cut -d'=' -f2- || true)"
    rm -f "${tmp_old}.clean"
  fi
  rm -f "${tmp_old}"

  # Готовим новый .env: шаблон + подстановка секретов.
  local tmp_new; tmp_new="$(mktemp)"
  cp .env.production.example "${tmp_new}"
  if [ -n "${wb_token:-}" ] && [[ "${wb_token}" != *"<<<"* ]]; then
    # `|` как разделитель sed — токены содержат `/` и `+`.
    sed -i.bak "s|^WB_TOKEN=.*|WB_TOKEN=${wb_token}|" "${tmp_new}" && rm -f "${tmp_new}.bak"
    echo "  - WB_TOKEN перенёс из старого .env"
  fi
  if [ -n "${jwt_key:-}" ] && [[ "${jwt_key}" != *"<<<"* ]]; then
    sed -i.bak "s|^JWT_SECRET_KEY=.*|JWT_SECRET_KEY=${jwt_key}|" "${tmp_new}" && rm -f "${tmp_new}.bak"
    echo "  - JWT_SECRET_KEY перенёс из старого .env"
  fi
  if [ -n "${tg_token:-}" ] && [[ "${tg_token}" != *"<<<"* ]]; then
    sed -i.bak "s|^# TG_BOT_TOKEN=.*|TG_BOT_TOKEN=${tg_token}|" "${tmp_new}" && rm -f "${tmp_new}.bak"
    echo "  - TG_BOT_TOKEN перенёс из старого .env"
  fi

  echo "→ Заливаю новый .env на сервер…"
  rsync -az "${tmp_new}" "${SERVER}:${REMOTE_DIR}/.env"
  rm -f "${tmp_new}"

  echo "→ Перезапускаю backend, workers, beat, bot чтобы подхватить .env…"
  ssh_cmd "cd ${REMOTE_DIR} && docker compose restart backend worker-stats worker-advert worker-default beat bot"

  echo
  echo "✓ .env обновлён."
  echo "  Если поля WB_TOKEN/JWT_SECRET_KEY всё ещё содержат <<<...>>> — значит"
  echo "  старый .env был полностью испорчен, заполни их вручную:"
  echo "      ssh ${SERVER}"
  echo "      nano ${REMOTE_DIR}/.env"
}

cmd_logs() {
  local svc="${1:-}"
  ssh_cmd "cd ${REMOTE_DIR} && docker compose logs --tail=200 -f ${svc}"
}

cmd_shell() {
  local svc="${1:-backend}"
  echo "→ Открываю shell в контейнере '${svc}' (Ctrl+D для выхода)"
  ssh -t "${SERVER}" "cd ${REMOTE_DIR} && docker compose exec ${svc} sh"
}

cmd_help() {
  cat <<HELP
remote.sh — управление сервером РНП с локальной машины.

Использование: $0 <команда> [args]

Команды:
  setup              [одноразово] поставить docker + подготовить ${REMOTE_DIR}
  deploy             rsync + АВТО-БЭКАП + docker compose up -d --build
                     (первый запуск создаст .env-шаблон, потребуется его заполнить)
  backup [label]     сделать бэкап БД вручную (label идёт в имя файла)
  restore <file>     восстановить из бэкапа (file = имя из ls backups/)
  status             docker compose ps на сервере
  logs [service]     хвост логов сервиса (frontend/backend/beat/...)
  shell [service]    открыть shell в контейнере (default: backend)
  push-env           залить свежий .env-шаблон на сервер, сохранив секреты
                     (помогает если старый .env испорчен по кодировке)
  help               эта справка

Переменные окружения (можно переопределить):
  SERVER=${SERVER}
  REMOTE_DIR=${REMOTE_DIR}
  PUBLIC_IP=${PUBLIC_IP}
  PORT=${PORT}

ВАЖНОЕ ПРАВИЛО — БЭКАПЫ:
  Команда 'deploy' автоматически делает pg_dump перед накаткой кода
  (если postgres запущен). Бэкапы лежат в ${REMOTE_DIR}/backups/ и
  не удаляются автоматически. Для ручного бэкапа — './scripts/remote.sh backup'.
  Перед командой 'restore' тоже делается бэкап текущего состояния.

ФЛАГИ ДЕПЛОЯ:
  FORCE=1 ./scripts/remote.sh deploy
      Пропускает диалог о активных celery-задачах. Деплой пойдёт сразу
      (но всё равно с warm shutdown до 30 мин).

  FAST=1 ./scripts/remote.sh deploy
      Быстрый деплой без warm shutdown воркеров. Шлёт SIGKILL через 10 сек.
      Активные задачи вернутся в очередь автоматически (acks_late+
      reject_on_worker_lost) и подхватятся новым воркером. Подходит когда
      нужно срочно задеплоить (UI-фиксы и т.п.).

  WAIT_MAX_SEC=N ./scripts/remote.sh deploy
      Максимальное время ожидания активных задач в pre-flight (default 1800).
HELP
}

cmd="${1:-help}"
shift || true
case "${cmd}" in
  setup)   cmd_setup ;;
  deploy)  cmd_deploy ;;
  backup)  cmd_backup "$@" ;;
  restore) cmd_restore "$@" ;;
  status)  cmd_status ;;
  logs)    cmd_logs "$@" ;;
  shell)   cmd_shell "$@" ;;
  push-env) cmd_push_env ;;
  help|-h|--help|"") cmd_help ;;
  *) echo "Неизвестная команда: ${cmd}"; cmd_help; exit 1 ;;
esac
