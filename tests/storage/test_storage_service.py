"""Tests for storage backends."""
import unittest, os, tempfile
from app.services import storage

class StorageTests(unittest.TestCase):
    def test_local_upload_download(self):
        # Force local backend
        old = os.environ.get("BACKUP_STORAGE_TYPE")
        os.environ["BACKUP_STORAGE_TYPE"] = "local"
        try:
            data = b"test backup data"
            key = "test-file.zip"
            loc = storage.upload(data, key)
            self.assertTrue(os.path.exists(loc))
            downloaded = storage.download(key)
            self.assertEqual(downloaded, data)
            storage.delete(key)
            self.assertFalse(os.path.exists(loc))
        finally:
            if old is None:
                os.environ.pop("BACKUP_STORAGE_TYPE", None)
            else:
                os.environ["BACKUP_STORAGE_TYPE"] = old

if __name__ == "__main__":
    unittest.main()
