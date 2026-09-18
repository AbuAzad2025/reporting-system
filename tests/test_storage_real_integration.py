"""
Real (non-mocked) integration tests for storage backends.

Uses the BACKUP_STORAGE_TYPE env var (default: local).
For S3 / Azure / GCS to run as real tests, set:
  BACKUP_STORAGE_TYPE=s3 + S3_BUCKET/S3_ACCESS_KEY/S3_SECRET_KEY
  BACKUP_STORAGE_TYPE=azure + AZURE_STORAGE_CONNECTION_STRING
  BACKUP_STORAGE_TYPE=gcs + GCS_BUCKET/GCS_CREDENTIALS

If credentials are missing for a cloud backend, the test skips.
"""
import unittest, os, tempfile
from app.services import storage


class StorageRealIntegrationTests(unittest.TestCase):
    def setUp(self):
        self._old_type = os.environ.get("BACKUP_STORAGE_TYPE")
        self.test_key = "integration-test-blob.zip"
        self.test_data = b"AZADEXA-REAL-TEST-DATA-2026"

    def tearDown(self):
        if self._old_type is None:
            os.environ.pop("BACKUP_STORAGE_TYPE", None)
        else:
            os.environ["BACKUP_STORAGE_TYPE"] = self._old_type
        try:
            storage.delete(self.test_key)
        except Exception:
            pass

    def test_local_real_roundtrip(self):
        """Always runs — filesystem is always available."""
        os.environ["BACKUP_STORAGE_TYPE"] = "local"
        loc = storage.upload(self.test_data, self.test_key)
        self.assertTrue(os.path.exists(loc))
        downloaded = storage.download(self.test_key)
        self.assertEqual(downloaded, self.test_data)
        storage.delete(self.test_key)
        self.assertFalse(os.path.exists(loc))

    def test_cloud_s3_real_or_skip(self):
        backend = os.environ.get("BACKUP_STORAGE_TYPE", "local").strip().lower()
        if backend != "s3":
            self.skipTest("BACKUP_STORAGE_TYPE != s3")
        if not (os.environ.get("S3_BUCKET") and os.environ.get("S3_ACCESS_KEY")):
            self.skipTest("S3 env vars missing — set S3_BUCKET + S3_ACCESS_KEY + S3_SECRET_KEY")
        loc = storage.upload(self.test_data, self.test_key)
        self.assertTrue(loc.startswith("s3://"))
        downloaded = storage.download(self.test_key)
        self.assertEqual(downloaded, self.test_data)
        storage.delete(self.test_key)

    def test_cloud_azure_real_or_skip(self):
        backend = os.environ.get("BACKUP_STORAGE_TYPE", "local").strip().lower()
        if backend != "azure":
            self.skipTest("BACKUP_STORAGE_TYPE != azure")
        if not os.environ.get("AZURE_STORAGE_CONNECTION_STRING"):
            self.skipTest("AZURE_STORAGE_CONNECTION_STRING missing")
        loc = storage.upload(self.test_data, self.test_key)
        self.assertTrue(loc.startswith("azure://"))
        downloaded = storage.download(self.test_key)
        self.assertEqual(downloaded, self.test_data)
        storage.delete(self.test_key)

    def test_cloud_gcs_real_or_skip(self):
        backend = os.environ.get("BACKUP_STORAGE_TYPE", "local").strip().lower()
        if backend != "gcs":
            self.skipTest("BACKUP_STORAGE_TYPE != gcs")
        if not (os.environ.get("GCS_BUCKET") or os.environ.get("GCS_CREDENTIALS")):
            self.skipTest("GCS env vars missing — set GCS_BUCKET or GCS_CREDENTIALS")
        loc = storage.upload(self.test_data, self.test_key)
        self.assertTrue(loc.startswith("gs://"))
        downloaded = storage.download(self.test_key)
        self.assertEqual(downloaded, self.test_data)
        storage.delete(self.test_key)

    def test_backup_serialization_real_roundtrip(self, app):
        with app.app_context():
            from app.services.backup import build_backup, validate_backup, restore_backup
            data = build_backup()
            self.assertTrue(validate_backup(data)["ok"])
            counts = restore_backup(data, project_id=None, replace=False)
            self.assertIsInstance(counts, dict)


if __name__ == "__main__":
    unittest.main()
