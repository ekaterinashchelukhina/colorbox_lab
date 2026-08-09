#!/usr/bin/env bash
# Ежедневный дамп БД с ротацией. Запускается через deploy/colorbox-backup.timer.
#
# ВАЖНО: это защищает от "случайно уронили таблицу" / "неудачная миграция", но НЕ от
# потери самого сервера (диск умер, VPS снесли) — дампы лежат на той же машине, что и
# рабочая БД. Как появится S3 — добавить сюда выгрузку архива за пределы сервера
# (например, `aws s3 cp` / `rclone copy`) вместо (или в дополнение к) локальной ротации.
set -euo pipefail

BACKUP_DIR="/var/backups/colorbox"
RETENTION_DAYS=14
DATABASE_URL="${DATABASE_URL:?DATABASE_URL не задан — запускать через systemd unit с EnvironmentFile}"

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

echo "Бэкап сохранён: $DUMP_FILE"