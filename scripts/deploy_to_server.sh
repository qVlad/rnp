#!/usr/bin/env bash
# Compat shim. Перенаправляет на новый универсальный remote.sh deploy.
# Сам скрипт см. ./scripts/remote.sh
exec "$(dirname "$0")/remote.sh" deploy "$@"
