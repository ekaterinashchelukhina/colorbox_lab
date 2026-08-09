"""Абстракция над хранилищем загружаемых файлов (фото заказов и смен).

Сегодня единственная реализация — локальный диск (LocalStorage). Когда понадобится
S3/MinIO: добавить класс S3Storage(Storage) с тем же контрактом save()/delete() и
подменить объект storage ниже (например, по переменной окружения) — utils.py и
роутеры трогать не придётся, они работают только через этот интерфейс.
"""
import os
from abc import ABC, abstractmethod


class Storage(ABC):
    @abstractmethod
    def save(self, key: str, data: bytes, content_type: str = "image/jpeg") -> str:
        """Сохраняет данные под key, возвращает URL, по которому файл потом отдаётся клиенту."""

    @abstractmethod
    def delete(self, url: str) -> None:
        """Удаляет файл по URL, ранее возвращённому save(). Молча ничего не делает, если файла
        уже нет — вызывающему коду не важно, было там что-то или нет."""


class LocalStorage(Storage):
    """Хранит файлы на локальном диске, отдаёт их через StaticFiles (см. main.py).

    Не переживает передеплой на эфемерной ФС (типичной для контейнерных PaaS без
    примонтированного persistent volume) и не годится для нескольких инстансов
    приложения за балансировщиком — файл, сохранённый на одном инстансе, не виден
    другому. Годится только для однономестного/dev-деплоя — до перехода на S3.
    """

    def __init__(self, directory: str, url_prefix: str):
        self._directory = directory
        self._url_prefix = url_prefix.rstrip("/")
        os.makedirs(directory, exist_ok=True)

    def save(self, key: str, data: bytes, content_type: str = "image/jpeg") -> str:
        path = os.path.join(self._directory, key)
        with open(path, "wb") as f:
            f.write(data)
        return f"{self._url_prefix}/{key}"

    def delete(self, url: str) -> None:
        key = url.rsplit("/", 1)[-1]
        path = os.path.join(self._directory, key)
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


UPLOAD_DIR = "static/uploads"
storage: Storage = LocalStorage(directory=UPLOAD_DIR, url_prefix=f"/{UPLOAD_DIR}")