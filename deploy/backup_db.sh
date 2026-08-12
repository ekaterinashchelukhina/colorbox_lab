#!/usr/bin/env bash
# Ежедневный дамп БД с ротацией. Запускается через deploy/colorbox-backup.timer.
#
# ВАЖНО: локальный дамп защищает от "случайно уронили таблицу" / "неудачная миграция",
# но НЕ от потери самого сервера (диск умер, VPS снесли) — поэтому дамп ещё и
# заливается в S3 (scripts/backup_to_s3.py, тот же бакет, что и фото, папка
# db-backups/) — это и есть выгрузка архива за пределы сервера. Если S3_BUCKET не
# задан в окружении сервиса, заливка сама себя пропускает без ошибки — локальный
# дамп при этом всё равно делается и ротируется.
set -euo pipefail

BACKUP_DIR="/var/backups/colorbox"
RETENTION_DAYS=14
DATABASE_URL="${DATABASE_URL:?DATABASE_URL не задан — запускать через systemd unit с EnvironmentFile}"
PYTHON_BIN="${PYTHON_BIN:-/var/www/.venv/bin/python3}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$BACKUP_DIR"

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
DUMP_FILE="$BACKUP_DIR/colorbox_${TIMESTAMP}.sql.gz"

pg_dump "$DATABASE_URL" | gzip > "$DUMP_FILE"

# Убедились, что дамп не пустой/битый, прежде чем чистить старые копии.
if [ ! -s "$DUMP_FILE" ]; then
    echo "Бэкап $DUMP_FILE пустой или не создался — старые копии не трогаем." >&2
    exit 1
fi

find "$BACKUP_DIR" -name "colorbox_*.sql.gz" -mtime "+${RETENTION_DAYS}" -delete

# Локальная копия уже сделана и отротирована к этому моменту — если заливка в S3
# упадёт (сеть, протухший ключ), это не должно стереть/пропустить локальную ротацию
# выше, но должно быть видно в journalctl как ошибка задания, а не потеряться молча.
if ! "$PYTHON_BIN" "$SCRIPT_DIR/../scripts/backup_to_s3.py" "$DUMP_FILE" "$RETENTION_DAYS"; then
    echo "Заливка бэкапа в S3 не удалась — локальная копия на месте, разберитесь вручную." >&2
    exit 1
fi

echo "Бэкап сохранён: $DUMP_FILE"