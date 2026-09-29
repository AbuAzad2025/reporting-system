"""Quick test for organized image upload."""
import unittest
import os
from app.services.storage import upload_image


def _backup_root():
    from app.services import storage
    return storage.BACKUP_LOCAL_DIR


class ImageStorageTests(unittest.TestCase):
    def test_upload_image_organized(self):
        data = b"fake_image_bytes"
        key = upload_image("Alpha Tower", "photo.jpg", data)
        # A key relative to the backup root, not a path on this machine: an
        # absolute value in the database breaks the moment the application
        # moves, and gives a browser no URL to fetch.
        self.assertFalse(os.path.isabs(key))
        self.assertIn("images/Alpha_Tower/", key.replace(os.sep, "/"))
        stored = os.path.join(_backup_root(), key.replace("/", os.sep))
        self.assertTrue(os.path.isfile(stored))
        with open(stored, "rb") as handle:
            self.assertEqual(handle.read(), data)
        os.remove(stored)
