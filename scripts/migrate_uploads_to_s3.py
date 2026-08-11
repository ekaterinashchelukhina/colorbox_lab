"""Разовая заливка уже существующих фото (static/uploads/) в S3-бакет — шаг перед
переключением STORAGE_BACKEND=s3 в проде (см. storage.py). Не трогает базу данных:
URL в БД уже хранится в бэкенд-независимом виде ("/static/uploads/{key}"), так что
после переноса файлов и рестарта приложения старые ссылки на фото продолжат работать
без изменений.

Запуск на сервере (там, где реально лежат файлы):
    export S3_BUCKET=colorbox-lab-photos
    export S3_ENDPOINT_URL=https://storage.yandexcloud.net   # опционально, это и так дефолт
    export S3_REGION=ru-central1                              # опционально, это и так дефолт
    export AWS_ACCESS_KEY_ID=...
    export AWS_SECRET_ACCESS_KEY=...
    python scripts/migrate_uploads_to_s3.py

Идемпотентен: уже залитые файлы (есть в бакете под тем же именем) пропускаются, так
что скрипт можно смело перезапускать при обрыве на середине.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import boto3
from botocore.exceptions import ClientError

from storage import UPLOAD_DIR


def object_exists(client, bucket: str, key: str) -> bool:
    try:
        client.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey"):
            return False
        raise


def main() -> None:
    bucket = os.environ["S3_BUCKET"]
    endpoint_url = os.getenv("S3_ENDPOINT_URL", "https://storage.yandexcloud.net")
    region_name = os.getenv("S3_REGION", "ru-central1")
    client = boto3.client("s3", endpoint_url=endpoint_url, region_name=region_name)

    if not os.path.isdir(UPLOAD_DIR):
        print(f"Каталог {UPLOAD_DIR} не найден — переносить нечего.")
        return

    filenames = sorted(
        name for name in os.listdir(UPLOAD_DIR) if os.path.isfile(os.path.join(UPLOAD_DIR, name))
    )
    total = len(filenames)
    uploaded = skipped = failed = 0

    for i, name in enumerate(filenames, start=1):
        try:
            if object_exists(client, bucket, name):
                skipped += 1
            else:
                with open(os.path.join(UPLOAD_DIR, name), "rb") as f:
                    client.put_object(Bucket=bucket, Key=name, Body=f.read(), ContentType="image/jpeg")
                uploaded += 1
        except Exception as e:
            failed += 1
            print(f"[{i}/{total}] ОШИБКА на {name}: {e}")
            continue

        if i % 50 == 0 or i == total:
            print(f"[{i}/{total}] загружено: {uploaded}, уже было: {skipped}, ошибок: {failed}")

    print(f"\nГотово. Всего файлов: {total}. Загружено: {uploaded}. Уже было в бакете: {skipped}. Ошибок: {failed}.")
    if failed:
        print("Есть ошибки — перезапустите скрипт ещё раз, он пропустит уже перенесённые файлы.")


if __name__ == "__main__":
    main()
