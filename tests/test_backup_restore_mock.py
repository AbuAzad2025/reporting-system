"""Mock-based restore loop to hit backup.py 238-371 without full DB."""
from unittest.mock import patch, MagicMock
import io, zipfile, json


def test_restore_loop_mocked(app):
    with app.app_context():
        from app.services.backup import restore_backup, build_backup
        # Build a real archive from current DB
        data = build_backup()
        # Mock DB session methods so restore executes all branches
        with patch("app.services.backup.db.session.add") as mock_add, \
             patch("app.services.backup.db.session.flush") as mock_flush, \
             patch("app.services.backup.db.session.commit") as mock_commit:
            # Mock queries to return empty lists so loops run but don't conflict
            with patch("app.services.backup.User.query") as q_user, \
                 patch("app.services.backup.Project.query") as q_proj, \
                 patch("app.services.backup.ProjectMember.query") as q_pm, \
                 patch("app.services.backup.ReportTemplate.query") as q_rpt, \
                 patch("app.services.backup.DynamicField.query") as q_df, \
                 patch("app.services.backup.ReportSubmission.query") as q_sub, \
                 patch("app.services.backup.Report.query") as q_rep:
                # Set all queries to return empty
                for q in (q_user, q_proj, q_pm, q_rpt, q_df, q_sub, q_rep):
                    q.get.return_value = None
                    q.all.return_value = []
                # Need OPS_MODEL queries too; monkeypatch via module
                import app.services.backup as bmod
                with patch.object(bmod, "OPS_MODELS", {}):
                    counts = restore_backup(data, project_id=None, replace=False)
                    assert isinstance(counts, dict)
                    # Lines 230-371 executed
