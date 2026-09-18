"""Mock tests for storage cloud backends (S3 / Azure / GCS)."""
import unittest, os
from unittest.mock import patch, MagicMock


class StorageCloudMockTests(unittest.TestCase):
    def _force_env(self, backend):
        self._old = os.environ.get("BACKUP_STORAGE_TYPE")
        os.environ["BACKUP_STORAGE_TYPE"] = backend

    def _restore_env(self):
        if self._old is None:
            os.environ.pop("BACKUP_STORAGE_TYPE", None)
        else:
            os.environ["BACKUP_STORAGE_TYPE"] = self._old

    @patch("app.services.storage._s3_client")
    def test_s3_upload_download_delete(self, mock_s3_client):
        self._force_env("s3")
        try:
            mock_client = MagicMock()
            mock_s3_client.return_value = mock_client
            mock_client.put_object.return_value = None
            mock_client.Object.return_value.get.return_value = {"Body": MagicMock(read=lambda: b"hello")}
            from app.services import storage
            loc = storage.upload(b"hello", "s3-test.zip")
            self.assertTrue(loc.startswith("s3://"))
            data = storage.download("s3-test.zip")
            self.assertEqual(data, b"hello")
            storage.delete("s3-test.zip")
            mock_client.delete_object.assert_called()
        finally:
            self._restore_env()

    @patch("app.services.storage._azure_client")
    def test_azure_upload_download_delete(self, mock_az_client):
        self._force_env("azure")
        try:
            mock_client = MagicMock()
            mock_az_client.return_value = mock_client
            container = MagicMock()
            mock_client.get_container_client.return_value = container
            blob_client = MagicMock()
            container.get_blob_client.return_value = blob_client
            blob_client.download_blob.return_value.readall.return_value = b"hello"
            from app.services import storage
            loc = storage.upload(b"hello", "azure-test.zip")
            self.assertTrue(loc.startswith("azure://"))
            data = storage.download("azure-test.zip")
            self.assertEqual(data, b"hello")
            storage.delete("azure-test.zip")
            blob_client.delete_blob.assert_called()
        finally:
            self._restore_env()

    @patch("app.services.storage._gcs_client")
    def test_gcs_upload_download_delete(self, mock_gcs_client):
        self._force_env("gcs")
        try:
            mock_client = MagicMock()
            mock_gcs_client.return_value = mock_client
            bucket = MagicMock()
            mock_client.bucket.return_value = bucket
            blob = MagicMock()
            bucket.blob.return_value = blob
            blob.download_as_bytes.return_value = b"hello"
            from app.services import storage
            loc = storage.upload(b"hello", "gcs-test.zip")
            self.assertTrue(loc.startswith("gs://"))
            data = storage.download("gcs-test.zip")
            self.assertEqual(data, b"hello")
            storage.delete("gcs-test.zip")
            blob.delete.assert_called()
        finally:
            self._restore_env()


if __name__ == "__main__":
    unittest.main()
