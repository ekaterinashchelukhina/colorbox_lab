"""Заливает свежий дамп БД в тот же S3-бакет, что и фото (storage.py) — в отдельную
папку db-backups/, чтобы не путать с фото — и чистит там копии старше retention_days.
Вызывается из deploy/backup_db.sh после того, как локальный дамп уже создан и
проверен на пустоту.

Если S3_BUCKET не задан — тихо ничего не делает и завершается успешно: заливка в S3
дополняет локальный бэкап, а не заменяет его, так что отсутствие настройки S3 не
должно валить весь бэкап-джоб.

Использование: python scripts/backup_to_s3.py <путь_к_дампу> [retention_days]
"""
import os
import sys
from datetime import datetime, timedelta, timezone

PREFIX = "db-backups/"


def main() -> None:
    bucket = os.getenv("S3_BUCKET")
    if not bucket:
        print("S3_BUCKET не задан — заливка бэкапа в S3 пропущена.")
        return

    dump_path = sys.argv[1]
    retention_days = int(sys.argv[2]) if len(sys.argv) > 2 else 14

    import boto3

    endpoint_url = os.getenv("S3_ENDPOINT_URL", "https://storage.yandexcloud.net")
    region_name = os.getenv("S3_REGION", "ru-central1")
    client = boto3.client("s3", endpoint_url=endpoint_url, region_name=region_name)

    key = PREFIX + os.path.basename(dump_path)
    with open(dump_path, "rb") as f:
        client.put_object(Bucket=bucket, Key=key, Body=f.read(), ContentType="application/gzip")
    print(f"Залито в S3: s3://{bucket}/{key}")

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    paginator = client.get_paginator("list_objects_v2")
    removed = 0
    for page in paginator.paginate(Bucket=bucket, Prefix=PREFIX):
        for obj in page.get("Contents", []):
            if obj["LastModified"] < cutoff:
                client.delete_object(Bucket=bucket, Key=obj["Key"])
                removed += 1
    if removed:
        print(f"Удалено старых бэкапов в S3: {removed}")


if __name__ == "__main__":
    main()