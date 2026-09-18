"""Quick test for organized image upload."""
import unittest
import os
from app.services.storage import upload_image


class ImageStorageTests(unittest.TestCase):
    def test_upload_image_organized(self):
        data = b"fake_image_bytes"
        result = upload_image("Alpha Tower", "photo.jpg", data)
        self.assertTrue(os.path.exists(result))
        self.assertIn("images/Alpha_Tower/", result)
        if os.path.exists(result):
            os.remove(result)
