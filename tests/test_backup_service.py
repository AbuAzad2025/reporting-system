"""Tests for backup serialization service."""
import unittest, zipfile, io
from app.services import backup

class BackupTests(unittest.TestCase):
    def test_backup_filename(self):
        from app.services.backup import backup_filename
        n = backup_filename()
        self.assertTrue(n.startswith("azadexa-full-backup-"))
        self.assertTrue(n.endswith(".zip"))

    def test_validate_backup_bad_zip(self):
        from app.services.backup import validate_backup
        res = validate_backup(b"not a zip")
        self.assertFalse(res["ok"])

    def test_build_and_restore(self):
        from app.services.backup import build_backup, restore_backup, validate_backup
        data = build_backup()
        v = validate_backup(data)
        self.assertTrue(v["ok"])
        # restore in isolation
        counts = restore_backup(data, project_id=None, replace=False)
        self.assertIsInstance(counts, dict)

if __name__ == "__main__":
    unittest.main()
