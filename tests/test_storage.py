"""Юнит-тесты на storage.py: контракт save()/open()/delete() для LocalStorage и
S3Storage (boto3 замокан — реальный бакет тут не нужен, важно только что вызываются
правильные S3-операции с правильными параметрами)."""
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from storage import LocalStorage, S3Storage


def test_local_storage_save_open_delete_roundtrip(tmp_path):
    storage = LocalStorage(directory=str(tmp_path), url_prefix="/static/uploads")

    url = storage.save("photo.jpg", b"hello", content_type="image/jpeg")
    assert url == "/static/uploads/photo.jpg"

    assert storage.open(url) == b"hello"

    storage.delete(url)
    assert storage.open(url) is None


def test_local_storage_delete_missing_file_is_noop(tmp_path):
    storage = LocalStorage(directory=str(tmp_path), url_prefix="/static/uploads")
    storage.delete("/static/uploads/never-existed.jpg")  # не должно бросать


def test_local_storage_open_missing_file_returns_none(tmp_path):
    storage = LocalStorage(directory=str(tmp_path), url_prefix="/static/uploads")
    assert storage.open("/static/uploads/never-existed.jpg") is None


@patch("boto3.client")
def test_s3_storage_save_returns_backend_independent_url(mock_boto_client):
    mock_client = MagicMock()
    mock_boto_client.return_value = mock_client

    storage = S3Storage(bucket="colorbox-lab-photos", endpoint_url="https://storage.yandexcloud.net",
                        region_name="ru-central1", url_prefix="/static/uploads")
    url = storage.save("order_5_detail.jpg", b"bytes", content_type="image/jpeg")

    # URL — тот же формат, что у LocalStorage, а не "сырой" S3-адрес: в БД он должен
    # оставаться бэкенд-независимым (см. docstring storage.py).
    assert url == "/static/uploads/order_5_detail.jpg"
    mock_client.put_object.assert_called_once_with(
        Bucket="colorbox-lab-photos", Key="order_5_detail.jpg", Body=b"bytes", ContentType="image/jpeg",
    )


@patch("boto3.client")
def test_s3_storage_open_returns_bytes(mock_boto_client):
    mock_client = MagicMock()
    mock_client.get_object.return_value = {"Body": MagicMock(read=lambda: b"photo-bytes")}
    mock_boto_client.return_value = mock_client

    storage = S3Storage(bucket="b", endpoint_url="https://storage.yandexcloud.net",
                        region_name="ru-central1", url_prefix="/static/uploads")
    result = storage.open("/static/uploads/order_5_detail.jpg")

    assert result == b"photo-bytes"
    mock_client.get_object.assert_called_once_with(Bucket="b", Key="order_5_detail.jpg")


@patch("boto3.client")
def test_s3_storage_open_missing_key_returns_none(mock_boto_client):
    mock_client = MagicMock()
    mock_client.get_object.side_effect = ClientError(
        error_response={"Error": {"Code": "NoSuchKey"}}, operation_name="GetObject",
    )
    mock_boto_client.return_value = mock_client

    storage = S3Storage(bucket="b", endpoint_url="https://storage.yandexcloud.net",
                        region_name="ru-central1", url_prefix="/static/uploads")
    assert storage.open("/static/uploads/missing.jpg") is None


@patch("boto3.client")
def test_s3_storage_open_reraises_other_errors(mock_boto_client):
    mock_client = MagicMock()
    mock_client.get_object.side_effect = ClientError(
        error_response={"Error": {"Code": "AccessDenied"}}, operation_name="GetObject",
    )
    mock_boto_client.return_value = mock_client

    storage = S3Storage(bucket="b", endpoint_url="https://storage.yandexcloud.net",
                        region_name="ru-central1", url_prefix="/static/uploads")
    with pytest.raises(ClientError):
        storage.open("/static/uploads/forbidden.jpg")


@patch("boto3.client")
def test_s3_storage_delete_calls_delete_object(mock_boto_client):
    mock_client = MagicMock()
    mock_boto_client.return_value = mock_client

    storage = S3Storage(bucket="b", endpoint_url="https://storage.yandexcloud.net",
                        region_name="ru-central1", url_prefix="/static/uploads")
    storage.delete("/static/uploads/order_5_detail.jpg")

    mock_client.delete_object.assert_called_once_with(Bucket="b", Key="order_5_detail.jpg")
