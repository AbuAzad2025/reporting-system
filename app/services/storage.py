"""
Storage backends for Azadexa Cloud backups.

Backend abstraction layer that supports:
  - local filesystem (default, for self-hosted and development)
  - Amazon S3 (boto3)
  - Azure Blob Storage (azure-storage-blob)
  - Google Cloud Storage (google-cloud-storage)

Configuration is read from environment variables at import time:
  BACKUP_STORAGE_TYPE (local | s3 | azure | gcs)
  S3_BUCKET, S3_REGION, S3_ACCESS_KEY, S3_SECRET_KEY
  AZURE_STORAGE_CONNECTION_STRING, AZURE_STORAGE_CONTAINER
  GCS_BUCKET, GCS_CREDENTIALS
"""
import io
import os
from datetime import datetime
from typing import Any, Dict, Optional


BACKUP_LOCAL_DIR = os.environ.get(
    "BACKUP_LOCAL_DIR",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "backups"))


def _local_dir() -> str:
    """Ensure the local backup directory exists."""
    os.makedirs(BACKUP_LOCAL_DIR, exist_ok=True)
    return BACKUP_LOCAL_DIR


def _storage_type() -> str:
    """Return configured storage backend type."""
    return os.environ.get("BACKUP_STORAGE_TYPE", "local").strip().lower()


def _s3_client() -> Any:
    """Lazy import and return boto3 S3 client."""
    import boto3
    return boto3.client(
        "s3",
        region_name=os.environ.get("S3_REGION", "us-east-1"),
        aws_access_key_id=os.environ.get("S3_ACCESS_KEY"),
        aws_secret_access_key=os.environ.get("S3_SECRET_KEY"),
    )


def _azure_client() -> Any:
    """Lazy import and return Azure Blob client."""
    from azure.storage.blob import BlobServiceClient
    return BlobServiceClient.from_connection_string(
        os.environ["AZURE_STORAGE_CONNECTION_STRING"])


def _gcs_client() -> Any:
    """Lazy import and return Google Cloud Storage client."""
    from google.cloud import storage
    credentials_path = os.environ.get("GCS_CREDENTIALS")
    if credentials_path:
        return storage.Client.from_service_account_json(credentials_path)
    return storage.Client()


def _bucket_name() -> str:
    """Return configured bucket/container name."""
    return os.environ.get("BACKUP_BUCKET_NAME", "azadexa-backups").strip()


def _container_name() -> str:
    """Return configured Azure container name."""
    return os.environ.get("AZURE_STORAGE_CONTAINER", "azadexa-backups").strip()


def _gcs_bucket(client: Any) -> Any:
    """Return GCS bucket object."""
    return client.bucket(_bucket_name())


def _blob_container(client: Any) -> Any:
    """Return Azure blob container object."""
    return client.get_container_client(_container_name())


def _gcs_blob(client: Any, key: str) -> Any:
    """Return GCS blob object."""
    return _gcs_bucket(client).blob(key)


def _s3_object(client: Any, key: str) -> Any:
    """Return S3 object handle."""
    return client.Object(_bucket_name(), key)


def _azure_blob(client: Any, key: str) -> Any:
    """Return Azure blob handle."""
    return _blob_container(client).get_blob_client(blob=key)


def _gcs_blob_handle(client: Any, key: str) -> Any:
    """Return GCS blob handle."""
    return _gcs_blob(client, key)


def _s3_key(key: str) -> str:
    """Return S3 key with prefix."""
    return os.path.join("backups", key)


def _azure_key(key: str) -> str:
    """Return Azure blob key with prefix."""
    return os.path.join("backups", key)


def _gcs_key(key: str) -> str:
    """Return GCS blob key with prefix."""
    return os.path.join("backups", key)


def _local_key(key: str) -> str:
    """Return local file path with prefix."""
    return os.path.join(_local_dir(), key)


def _to_bytes(data: Any) -> bytes:
    """Convert various input types to bytes."""
    if isinstance(data, bytes):
        return data
    if hasattr(data, "read"):
        return data.read()
    return str(data).encode("utf-8")


def _from_bytes(data: bytes) -> io.BytesIO:
    """Convert bytes to BytesIO stream."""
    return io.BytesIO(data)


def _s3_upload(data: bytes, key: str) -> str:
    """Upload to S3 and return the object URI."""
    client = _s3_client()
    s3_key = _s3_key(key)
    client.put_object(Bucket=_bucket_name(), Key=s3_key, Body=data)
    return f"s3://{_bucket_name()}/{s3_key}"


def _s3_download(key: str) -> bytes:
    """Download from S3 and return bytes."""
    client = _s3_client()
    s3_key = _s3_key(key)
    obj = _s3_object(client, s3_key)
    return obj.get()["Body"].read()


def _azure_upload(data: bytes, key: str) -> str:
    """Upload to Azure Blob Storage and return the URI."""
    client = _azure_client()
    azure_key = _azure_key(key)
    blob = _azure_blob(client, azure_key)
    blob.upload_blob(data, overwrite=True)
    return f"azure://{_container_name()}/{azure_key}"


def _azure_download(key: str) -> bytes:
    """Download from Azure Blob Storage and return bytes."""
    client = _azure_client()
    azure_key = _azure_key(key)
    blob = _azure_blob(client, azure_key)
    return blob.download_blob().readall()


def _gcs_upload(data: bytes, key: str) -> str:
    """Upload to Google Cloud Storage and return the URI."""
    client = _gcs_client()
    gcs_key = _gcs_key(key)
    blob = _gcs_blob_handle(client, gcs_key)
    blob.upload_from_string(data)
    return f"gs://{_bucket_name()}/{gcs_key}"


def _gcs_download(key: str) -> bytes:
    """Download from Google Cloud Storage and return bytes."""
    client = _gcs_client()
    gcs_key = _gcs_key(key)
    blob = _gcs_blob_handle(client, gcs_key)
    return blob.download_as_bytes()


def _local_upload(data: bytes, key: str) -> str:
    """Upload to local filesystem and return the file path."""
    local_key = _local_key(key)
    os.makedirs(os.path.dirname(local_key), exist_ok=True)
    with open(local_key, "wb") as fh:
        fh.write(data)
    return local_key


def _local_download(key: str) -> bytes:
    """Download from local filesystem and return bytes."""
    local_key = _local_key(key)
    with open(local_key, "rb") as fh:
        return fh.read()


def upload(data: bytes, key: str) -> str:
    """Upload backup data to the configured storage backend."""
    data = _to_bytes(data)
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    if not key:
        key = f"backup-{stamp}.zip"
    backend = _storage_type()
    if backend == "s3":
        return _s3_upload(data, key)
    if backend == "azure":
        return _azure_upload(data, key)
    if backend == "gcs":
        return _gcs_upload(data, key)
    return _local_upload(data, key)


def download(key: str) -> bytes:
    """Download backup data from the configured storage backend."""
    backend = _storage_type()
    if backend == "s3":
        return _s3_download(key)
    if backend == "azure":
        return _azure_download(key)
    if backend == "gcs":
        return _gcs_download(key)
    return _local_download(key)


def list_backups() -> list:
    """List backup objects in the configured storage backend."""
    backend = _storage_type()
    if backend == "s3":
        client = _s3_client()
        response = client.list_objects_v2(
            Bucket=_bucket_name(), Prefix="backups/")
        return [obj["Key"] for obj in response.get("Contents", [])]
    if backend == "azure":
        client = _azure_client()
        container = _blob_container(client)
        return [blob.name for blob in container.list_blobs(
            name_starts_with="backups/")]
    if backend == "gcs":
        client = _gcs_client()
        bucket = _gcs_bucket(client)
        return [blob.name for blob in bucket.list_blobs(
            prefix="backups/")]
    # local filesystem
    local_dir = _local_dir()
    return [os.path.join(local_dir, name) for name in os.listdir(local_dir)
            if os.path.isfile(os.path.join(local_dir, name))]


def delete(key: str) -> None:
    """Delete backup object from the configured storage backend."""
    backend = _storage_type()
    if backend == "s3":
        client = _s3_client()
        client.delete_object(Bucket=_bucket_name(), Key=_s3_key(key))
    elif backend == "azure":
        client = _azure_client()
        blob = _azure_blob(client, _azure_key(key))
        blob.delete_blob()
    elif backend == "gcs":
        client = _gcs_client()
        blob = _gcs_blob_handle(client, _gcs_key(key))
        blob.delete()
    else:
        os.remove(_local_key(key))


__all__ = [
    "upload",
    "download",
    "list_backups",
    "delete",
    "BACKUP_LOCAL_DIR",
]
