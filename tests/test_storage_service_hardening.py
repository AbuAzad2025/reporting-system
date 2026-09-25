"""Behavioural hardening tests for app.services.storage.

These exercise the real storage contract against throwaway state:
  * upload() payload coercion (str / BytesIO / bytes) + default key generation
  * local list_backups() -> download() -> delete() round trip on basenames
  * upload_image() traversal sanitisation + sequential numbering
  * local download() traversal rejection (error types preserved)
  * s3 / azure / gcs client factories wired from environment variables, using
    fake SDK modules injected into sys.modules (no network, no extra deps)
  * cloud list_backups() -> download() -> delete() with a single 'backups/'
    prefix, so keys handed back by the list are directly consumable

Nothing is written into the repository's app/backups: the local backend is
always re-rooted into tmp_path via monkeypatch.
"""
import io
import os
import re
import sys
import types

import pytest

from app.services import storage


BACKUP_ENV_VARS = (
    "BACKUP_STORAGE_TYPE",
    "BACKUP_BUCKET_NAME",
    "S3_REGION",
    "S3_ACCESS_KEY",
    "S3_SECRET_KEY",
    "AZURE_STORAGE_CONNECTION_STRING",
    "AZURE_STORAGE_CONTAINER",
    "GCS_CREDENTIALS",
)


def _read(path):
    with open(path, "rb") as fh:
        return fh.read()


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolated_backup_env(monkeypatch):
    """No ambient backup configuration leaks in from the developer machine."""
    for name in BACKUP_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture()
def backup_dir(tmp_path, monkeypatch):
    """Local backend rooted in tmp_path — never the repo's app/backups."""
    monkeypatch.setenv("BACKUP_STORAGE_TYPE", "local")
    root = tmp_path / "backups"
    monkeypatch.setattr(storage, "BACKUP_LOCAL_DIR", str(root))
    return root


# ---- fake cloud SDKs ------------------------------------------------------

class _S3Object:
    def __init__(self, store, ref):
        self._store = store
        self._ref = ref

    def get(self):
        return {"Body": io.BytesIO(self._store[self._ref])}


class FakeS3Client:
    """In-memory stand-in for a boto3 S3 client."""

    def __init__(self):
        self.objects = {}
        self.keys = []
        self.factory_calls = []

    def put_object(self, Bucket, Key, Body):
        self.keys.append(Key)
        self.objects[(Bucket, Key)] = bytes(Body)

    def Object(self, Bucket, Key):
        self.keys.append(Key)
        return _S3Object(self.objects, (Bucket, Key))

    def list_objects_v2(self, Bucket, Prefix):
        self.keys.append(Prefix)
        return {"Contents": [{"Key": key}
                             for bucket, key in sorted(self.objects)
                             if bucket == Bucket and key.startswith(Prefix)]}

    def delete_object(self, Bucket, Key):
        self.keys.append(Key)
        del self.objects[(Bucket, Key)]


def install_fake_boto3(monkeypatch):
    """Inject a fake ``boto3`` module; returns the shared fake client."""
    client = FakeS3Client()

    def _client(service_name, **kwargs):
        client.factory_calls.append((service_name, kwargs))
        return client

    module = types.ModuleType("boto3")
    module.client = _client
    monkeypatch.setitem(sys.modules, "boto3", module)
    return client


class _AzureDownload:
    def __init__(self, store, ref):
        self._store = store
        self._ref = ref

    def readall(self):
        return self._store[self._ref]


class FakeAzureBlobClient:
    def __init__(self, store, container, name):
        self._store = store
        self._ref = (container, name)

    def upload_blob(self, data, overwrite=False):
        self._store[self._ref] = bytes(data)

    def download_blob(self):
        return _AzureDownload(self._store, self._ref)

    def delete_blob(self):
        del self._store[self._ref]


class FakeAzureContainer:
    def __init__(self, store, name):
        self._store = store
        self._name = name

    def get_blob_client(self, blob):
        return FakeAzureBlobClient(self._store, self._name, blob)

    def list_blobs(self, name_starts_with=None):
        return [types.SimpleNamespace(name=name)
                for container, name in sorted(self._store)
                if container == self._name
                and (name_starts_with is None
                     or name.startswith(name_starts_with))]


class FakeAzureServiceClient:
    def __init__(self):
        self.store = {}
        self.connection_strings = []
        self.containers = []

    def get_container_client(self, container):
        self.containers.append(container)
        return FakeAzureContainer(self.store, container)


def install_fake_azure(monkeypatch):
    """Inject fake ``azure.storage.blob`` modules; returns the fake service."""
    service = FakeAzureServiceClient()

    class BlobServiceClient:
        @staticmethod
        def from_connection_string(connection_string, **kwargs):
            service.connection_strings.append(connection_string)
            return service

    blob_mod = types.ModuleType("azure.storage.blob")
    blob_mod.BlobServiceClient = BlobServiceClient
    storage_mod = types.ModuleType("azure.storage")
    storage_mod.blob = blob_mod
    azure_mod = types.ModuleType("azure")
    azure_mod.storage = storage_mod
    monkeypatch.setitem(sys.modules, "azure", azure_mod)
    monkeypatch.setitem(sys.modules, "azure.storage", storage_mod)
    monkeypatch.setitem(sys.modules, "azure.storage.blob", blob_mod)
    return service


class FakeGcsBlob:
    def __init__(self, store, bucket, name):
        self._store = store
        self._ref = (bucket, name)

    def upload_from_string(self, data):
        self._store[self._ref] = bytes(data)

    def download_as_bytes(self):
        return self._store[self._ref]

    def delete(self):
        del self._store[self._ref]


class FakeGcsBucket:
    def __init__(self, store, name):
        self._store = store
        self._name = name

    def blob(self, name):
        return FakeGcsBlob(self._store, self._name, name)

    def list_blobs(self, prefix=""):
        return [types.SimpleNamespace(name=name)
                for bucket, name in sorted(self._store)
                if bucket == self._name and name.startswith(prefix)]


class FakeGcsClient:
    def __init__(self):
        self.store = {}
        self.credential_paths = []
        self.buckets = []

    def bucket(self, name):
        self.buckets.append(name)
        return FakeGcsBucket(self.store, name)


def install_fake_gcs(monkeypatch):
    """Inject fake ``google.cloud.storage`` modules; returns the fake client."""
    service = FakeGcsClient()

    class Client:
        @staticmethod
        def from_service_account_json(path, *args, **kwargs):
            service.credential_paths.append(path)
            return service

        def __new__(cls, *args, **kwargs):
            # storage.Client() must land on the same fake instance
            return service

    gcs_mod = types.ModuleType("google.cloud.storage")
    gcs_mod.Client = Client
    cloud_mod = types.ModuleType("google.cloud")
    cloud_mod.storage = gcs_mod
    google_mod = types.ModuleType("google")
    google_mod.cloud = cloud_mod
    monkeypatch.setitem(sys.modules, "google", google_mod)
    monkeypatch.setitem(sys.modules, "google.cloud", cloud_mod)
    monkeypatch.setitem(sys.modules, "google.cloud.storage", gcs_mod)
    return service


@pytest.fixture()
def s3_backend(monkeypatch):
    monkeypatch.setenv("BACKUP_STORAGE_TYPE", "s3")
    monkeypatch.setenv("BACKUP_BUCKET_NAME", "azadexa-test-bucket")
    return install_fake_boto3(monkeypatch)


@pytest.fixture()
def azure_backend(monkeypatch):
    monkeypatch.setenv("BACKUP_STORAGE_TYPE", "azure")
    monkeypatch.setenv("BACKUP_BUCKET_NAME", "azadexa-test-container")
    monkeypatch.setenv("AZURE_STORAGE_CONTAINER", "azadexa-test-container")
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING",
                       "DefaultEndpointsProtocol=https;AccountName=test;")
    return install_fake_azure(monkeypatch)


@pytest.fixture()
def gcs_backend(monkeypatch):
    monkeypatch.setenv("BACKUP_STORAGE_TYPE", "gcs")
    monkeypatch.setenv("BACKUP_BUCKET_NAME", "azadexa-test-bucket")
    return install_fake_gcs(monkeypatch)


# --------------------------------------------------------------------------
# local backend: payload coercion + default key
# --------------------------------------------------------------------------

@pytest.mark.parametrize("payload,expected", [
    (b"raw-bytes", b"raw-bytes"),
    (io.BytesIO(b"streamed-bytes"), b"streamed-bytes"),
    ("نص عربي backup", "نص عربي backup".encode("utf-8")),
])
def test_upload_accepts_str_stream_and_bytes(backup_dir, payload, expected):
    path = storage.upload(payload, "payload.zip")
    assert path == str(backup_dir / "payload.zip")
    assert _read(path) == expected
    assert storage.download("payload.zip") == expected


def test_upload_without_key_generates_timestamped_default(backup_dir):
    path = storage.upload(b"auto-key", "")
    name = os.path.basename(path)
    assert re.fullmatch(r"backup-\d{8}-\d{6}\.zip", name)
    assert name in storage.list_backups()
    assert storage.download(name) == b"auto-key"
    storage.delete(name)
    assert not os.path.exists(path)


def test_upload_with_explicit_key_is_preserved(backup_dir):
    path = storage.upload("text-body", "azadexa-platform-20260101-000000.zip")
    assert os.path.basename(path) == "azadexa-platform-20260101-000000.zip"
    assert storage.download("azadexa-platform-20260101-000000.zip") == b"text-body"


# --------------------------------------------------------------------------
# local backend: list -> download -> delete
# --------------------------------------------------------------------------

def test_local_list_backups_returns_basenames_only(backup_dir):
    storage.upload(b"top-level", "top.zip")
    storage.upload(b"nested", os.path.join("nested", "inner.zip"))
    storage.upload_image("Alpha Tower", "photo.jpg", b"img")

    listed = storage.list_backups()

    # directories (images/, nested/) are not backups, and nested files are
    # not surfaced: the local contract is top-level basenames only.
    assert listed == ["top.zip"]
    assert all(os.sep not in name and "/" not in name for name in listed)
    assert storage.download(listed[0]) == b"top-level"


def test_local_list_download_delete_round_trip(backup_dir):
    storage.upload(b"payload-1", "alpha.zip")
    storage.upload(b"payload-2", "beta.zip")

    listed = sorted(storage.list_backups())
    assert listed == ["alpha.zip", "beta.zip"]

    for name, payload in (("alpha.zip", b"payload-1"), ("beta.zip", b"payload-2")):
        assert name in listed
        assert storage.download(name) == payload

    storage.delete("beta.zip")
    assert not (backup_dir / "beta.zip").exists()
    assert storage.list_backups() == ["alpha.zip"]
    with pytest.raises(FileNotFoundError):
        storage.download("beta.zip")


def test_local_download_rejects_path_traversal(backup_dir, tmp_path):
    outside = tmp_path / "outside-secret.txt"
    outside.write_bytes(b"TOP-SECRET")

    for key in (os.path.join("..", "outside-secret.txt"),
                os.path.join("..", "..", "outside-secret.txt"),
                str(outside)):
        with pytest.raises(ValueError):
            storage.download(key)

    assert _read(str(outside)) == b"TOP-SECRET"
    assert storage.list_backups() == []  # nothing leaked into the backup dir


def test_local_download_allows_keys_inside_backup_dir(backup_dir):
    """The guard rejects escapes only — nested in-tree keys still resolve."""
    storage.upload(b"inner", os.path.join("sub", "inner.zip"))
    assert storage.download(os.path.join("sub", "inner.zip")) == b"inner"


def test_local_download_missing_key_raises_file_not_found(backup_dir):
    with pytest.raises(FileNotFoundError):
        storage.download("does-not-exist.zip")


# --------------------------------------------------------------------------
# upload_image
# --------------------------------------------------------------------------

def test_upload_image_sanitizes_traversal_filename(backup_dir):
    posix_escape = storage.upload_image("Alpha Tower", "../../../etc/evil.jpg", b"pwned")
    windows_escape = storage.upload_image("Alpha Tower", "..\\..\\win.jpg", b"pwned")

    for path in (posix_escape, windows_escape):
        parts = os.path.relpath(path, str(backup_dir)).split(os.sep)
        assert parts[0] == "images"
        assert parts[1] == "Alpha_Tower"
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", parts[2])
        assert ".." not in parts
        assert os.path.basename(path) in ("evil_001.jpg", "win_001.jpg")

    assert os.path.basename(posix_escape) == "evil_001.jpg"
    assert _read(posix_escape) == b"pwned"
    # nothing escaped into the images tree or its parents
    assert not (backup_dir / "evil_001.jpg").exists()
    assert not (backup_dir / "images" / "evil_001.jpg").exists()
    files = [os.path.join(root, f)
             for root, _dirs, names in os.walk(str(backup_dir))
             for f in names]
    assert len(files) == 2


def test_upload_image_numbers_sequentially_per_project_and_date(backup_dir):
    first = storage.upload_image("Alpha Tower", "photo.jpg", b"one")
    second = storage.upload_image("Alpha Tower", "photo.jpg", b"two")
    third = storage.upload_image("Alpha Tower", "photo.jpg", b"three")

    assert [os.path.basename(p) for p in (first, second, third)] == [
        "photo_001.jpg", "photo_002.jpg", "photo_003.jpg"]
    assert len({os.path.dirname(p) for p in (first, second, third)}) == 1
    assert [_read(p) for p in (first, second, third)] == [b"one", b"two", b"three"]

    # a different project restarts the sequence in its own directory
    other = storage.upload_image("Beta Hospital", "photo.jpg", b"beta")
    assert os.path.dirname(other) != os.path.dirname(first)
    assert os.path.basename(other) == "photo_001.jpg"
    assert _read(other) == b"beta"


def test_upload_image_handles_degenerate_filenames(backup_dir):
    names = ["..", ".", "", "logo", "logo.", "....//....//deep.PNG"]
    paths = [storage.upload_image("Alpha Tower", name, b"bytes")
             for name in names]

    assert len(set(paths)) == len(names)
    for path in paths:
        rel = os.path.relpath(path, str(backup_dir))
        assert ".." not in rel.split(os.sep)
        assert os.path.dirname(path).startswith(
            str(backup_dir / "images" / "Alpha_Tower"))
        assert _read(path) == b"bytes"
    assert os.path.basename(paths[3]) == "logo_001.jpg"  # no extension -> .jpg
    assert os.path.basename(paths[5]) == "deep_001.PNG"  # case preserved


# --------------------------------------------------------------------------
# client factories read the documented environment variables
# --------------------------------------------------------------------------

def test_s3_client_factory_reads_documented_env(monkeypatch):
    client = install_fake_boto3(monkeypatch)
    monkeypatch.setenv("S3_REGION", "eu-west-1")
    monkeypatch.setenv("S3_ACCESS_KEY", "AKIA-TEST")
    monkeypatch.setenv("S3_SECRET_KEY", "secret-test")

    assert storage._s3_client() is client
    assert client.factory_calls == [("s3", {
        "region_name": "eu-west-1",
        "aws_access_key_id": "AKIA-TEST",
        "aws_secret_access_key": "secret-test",
    })]


def test_s3_client_factory_defaults(monkeypatch):
    client = install_fake_boto3(monkeypatch)

    assert storage._s3_client() is client
    assert client.factory_calls == [("s3", {
        "region_name": "us-east-1",
        "aws_access_key_id": None,
        "aws_secret_access_key": None,
    })]
    assert storage._bucket_name() == "azadexa-backups"


def test_azure_client_factory_reads_connection_string_and_container(monkeypatch):
    service = install_fake_azure(monkeypatch)
    conn = "DefaultEndpointsProtocol=https;AccountName=test;AccountKey=k;"
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", conn)
    monkeypatch.setenv("AZURE_STORAGE_CONTAINER", "backups-eu")

    assert storage._azure_client() is service
    assert service.connection_strings == [conn]
    assert isinstance(storage._blob_container(service), FakeAzureContainer)
    assert service.containers == ["backups-eu"]


def test_azure_client_factory_requires_connection_string(monkeypatch):
    """Documented behaviour: the connection string is mandatory (KeyError)."""
    install_fake_azure(monkeypatch)
    with pytest.raises(KeyError):
        storage._azure_client()
    assert storage._container_name() == "azadexa-backups"


def test_gcs_client_factory_prefers_service_account_json(monkeypatch, tmp_path):
    service = install_fake_gcs(monkeypatch)
    creds = tmp_path / "gcs-creds.json"
    creds.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("GCS_CREDENTIALS", str(creds))
    monkeypatch.setenv("BACKUP_BUCKET_NAME", "gcs-backups")

    assert storage._gcs_client() is service
    assert service.credential_paths == [str(creds)]
    assert isinstance(storage._gcs_bucket(service), FakeGcsBucket)
    assert service.buckets == ["gcs-backups"]


def test_gcs_client_factory_falls_back_to_default_credentials(monkeypatch):
    service = install_fake_gcs(monkeypatch)

    assert storage._gcs_client() is service
    assert service.credential_paths == []


# --------------------------------------------------------------------------
# cloud backends: list -> download -> delete without a doubled prefix
# --------------------------------------------------------------------------

@pytest.mark.parametrize("key_fn", ["_s3_key", "_azure_key", "_gcs_key"])
def test_cloud_keys_are_prefixed_exactly_once(key_fn):
    fn = getattr(storage, key_fn)
    assert fn("backup.zip") == "backups/backup.zip"
    assert fn("backups/backup.zip") == "backups/backup.zip"
    assert fn("nested/backup.zip") == "backups/nested/backup.zip"
    assert fn("backups/nested/backup.zip") == "backups/nested/backup.zip"


def test_s3_list_download_delete_round_trip(s3_backend):
    uri = storage.upload(b"s3 payload", "backup-a.zip")
    assert uri == "s3://azadexa-test-bucket/backups/backup-a.zip"

    listed = storage.list_backups()
    assert listed == ["backups/backup-a.zip"]
    assert storage.download(listed[0]) == b"s3 payload"
    # the bare key still works (upload/download API is unchanged)
    assert storage.download("backup-a.zip") == b"s3 payload"

    storage.delete(listed[0])
    assert storage.list_backups() == []
    assert s3_backend.objects == {}
    assert all("backups/backups/" not in key for key in s3_backend.keys)


def test_azure_list_download_delete_round_trip(azure_backend):
    uri = storage.upload(b"azure payload", "backup-b.zip")
    assert uri == "azure://azadexa-test-container/backups/backup-b.zip"

    listed = storage.list_backups()
    assert listed == ["backups/backup-b.zip"]
    assert storage.download(listed[0]) == b"azure payload"
    assert storage.download("backup-b.zip") == b"azure payload"

    storage.delete(listed[0])
    assert storage.list_backups() == []
    assert azure_backend.store == {}


def test_gcs_list_download_delete_round_trip(gcs_backend):
    uri = storage.upload(b"gcs payload", "backup-c.zip")
    assert uri == "gs://azadexa-test-bucket/backups/backup-c.zip"

    listed = storage.list_backups()
    assert listed == ["backups/backup-c.zip"]
    assert storage.download(listed[0]) == b"gcs payload"
    assert storage.download("backup-c.zip") == b"gcs payload"

    storage.delete(listed[0])
    assert storage.list_backups() == []
    assert gcs_backend.store == {}


def test_cloud_default_key_is_listed_and_consumable(s3_backend):
    """Empty key -> default name, still reachable through list -> download."""
    storage.upload(b"auto", "")
    listed = storage.list_backups()
    assert len(listed) == 1
    assert re.fullmatch(r"backups/backup-\d{8}-\d{6}\.zip", listed[0])
    assert storage.download(listed[0]) == b"auto"
    storage.delete(listed[0])
    assert s3_backend.objects == {}
