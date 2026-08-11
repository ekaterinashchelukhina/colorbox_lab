"""Абстракция над хранилищем загружаемых файлов (фото заказов и смен).

Две реализации: LocalStorage (локальный диск, дефолт) и S3Storage (Yandex Object
Storage/любой S3-совместимый бэкенд). Какая используется — решает переменная
окружения STORAGE_BACKEND, см. storage_from_env() внизу файла. utils.py и роутеры
работают только через интерфейс Storage — им всё равно, где физически лежат байты.

Важно: save() всегда возвращает URL вида "/static/uploads/{key}" независимо от
бэкенда — это тот же адрес, что отдаёт main.py:serve_uploaded_photo. Поэтому в БД
URL хранится в бэкенд-независимом формате, и переключение LocalStorage <-> S3Storage
не требует миграции уже сохранённых заказов/смен — только переноса самих файлов
(см. scripts/migrate_uploads_to_s3.py) и перезапуска приложения.
"""
import os
from abc import ABC, abstractmethod
from typing import Optional


class Storage(ABC):
    @abstractmethod
    def save(self, key: str, data: bytes, content_type: str = "image/jpeg") -> str:
        """Сохраняет данные под key, возвращает URL, по которому файл потом отдаётся клиенту."""

    @abstractmethod
    def delete(self, url: str) -> None:
        """Удаляет файл по URL, ранее возвращённому save(). Молча ничего не делает, если файла
        уже нет — вызывающему коду не важно, было там что-то или нет."""

    @abstractmethod
    def open(self, url: str) -> Optional[bytes]:
        """Читает байты файла по URL, ранее возвращённому save(). None, если файла нет —
        вызывающая сторона (main.py:serve_uploaded_photo) сама превращает это в 404."""


class LocalStorage(Storage):
    """Хранит файлы на локальном диске.

    Не переживает передеплой на эфемерной ФС (типичной для контейнерных PaaS без
    примонтированного persistent volume) и не годится для нескольких инстансов
    приложения за балансировщиком — файл, сохранённый на одном инстансе, не виден
    другому. Годится для одноместного/dev-деплоя — см. S3Storage для остальных случаев.
    """

    def __init__(self, directory: str, url_prefix: str):
        self._directory = directory
        self._url_prefix = url_prefix.rstrip("/")
        os.makedirs(directory, exist_ok=True)

    def _path_for(self, url: str) -> str:
        key = url.rsplit("/", 1)[-1]
        return os.path.join(self._directory, key)

    def save(self, key: str, data: bytes, content_type: str = "image/jpeg") -> str:
        with open(os.path.join(self._directory, key), "wb") as f:
            f.write(data)
        return f"{self._url_prefix}/{key}"

    def delete(self, url: str) -> None:
        try:
            os.remove(self._path_for(url))
        except FileNotFoundError:
            pass

    def open(self, url: str) -> Optional[bytes]:
        try:
            with open(self._path_for(url), "rb") as f:
                return f.read()
        except FileNotFoundError:
            return None


class S3Storage(Storage):
    """Yandex Object Storage (или любой S3-совместимый бэкенд) через boto3.

    Ключи доступа boto3 берёт сам из стандартных переменных окружения
    AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY — здесь их нет и не должно быть,
    чтобы секрет не оказался в коде/логах инициализации.
    """

    def __init__(self, bucket: str, endpoint_url: str, region_name: str, url_prefix: str):
        import boto3

        self._bucket = bucket
        self._client = boto3.client("s3", endpoint_url=endpoint_url, region_name=region_name)
        self._url_prefix = url_prefix.rstrip("/")

    def save(self, key: str, data: bytes, content_type: str = "image/jpeg") -> str:
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)
        return f"{self._url_prefix}/{key}"

    def delete(self, url: str) -> None:
        # delete_object в S3 API идемпотентен — не падает, если объекта уже нет.
        key = url.rsplit("/", 1)[-1]
        self._client.delete_object(Bucket=self._bucket, Key=key)

    def open(self, url: str) -> Optional[bytes]:
        from botocore.exceptions import ClientError

        key = url.rsplit("/", 1)[-1]
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            return response["Body"].read()
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                return None
            raise


UPLOAD_DIR = "static/uploads"
URL_PREFIX = f"/{UPLOAD_DIR}"


def storage_from_env() -> Storage:
    """STORAGE_BACKEND=s3 переключает на Yandex Object Storage (нужны S3_BUCKET и,
    как правило, S3_ENDPOINT_URL/S3_REGION уже со своими дефолтами под Yandex Cloud).
    Без неё — локальный диск, как раньше."""
    if os.getenv("STORAGE_BACKEND") == "s3":
        return S3Storage(
            bucket=os.environ["S3_BUCKET"],
            endpoint_url=os.getenv("S3_ENDPOINT_URL", "https://storage.yandexcloud.net"),
            region_name=os.getenv("S3_REGION", "ru-central1"),
            url_prefix=URL_PREFIX,
        )
    return LocalStorage(directory=UPLOAD_DIR, url_prefix=URL_PREFIX)


storage: Storage = storage_from_env()