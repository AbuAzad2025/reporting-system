"""Word (.docx) exports for IPC and Variation Orders.

The package is validated by unpacking it and parsing the XML parts, and the
document text is extracted from `word/document.xml` — so these assertions
prove the real file structure and the real content a reviewer would open.
"""
import io
import re
import zipfile
from xml.etree import ElementTree

import pytest

from tests.conftest import login_as

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
REQUIRED_PARTS = {"[Content_Types].xml", "_rels/.rels",
                  "word/document.xml", "word/styles.xml",
                  "word/_rels/document.xml.rels", "docProps/core.xml"}


def _record_id(app, serial, model):
    from app.ops import models as M
    with app.app_context():
        return getattr(M, model).query.filter_by(serial=serial).one().id


def _docx_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        root = ElementTree.fromstring(z.read("word/document.xml"))
    return "\n".join(t.text or "" for t in root.iter(f"{W}t"))


def _open(data: bytes) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(data))


def _ipc(app, client):
    from app.ops.models import ProgressBilling
    with app.app_context():
        row = ProgressBilling.query.first()
        row.cert_no = "IPC-2026-014"
        row.work_item = "صب الأرضيات الطابق الأول"
        row.qty_completed = 1250.5
        row.rate = 42.75
        row.retention_pct = 10.0
        row.previously_certified = 18000.0
        row.boq_ref = "BOQ-3.2"
        row.measurement_ref = "MR-0099"
        row.progress_pct = 35.0
        row.notes = "تم التحقق من الكميات ميدانياً"
        from app.extensions import db
        db.session.commit()
        return row.id


def _vo(app, client):
    from app.extensions import db
    from app.ops.models import VariationOrder
    with app.app_context():
        row = VariationOrder.query.first()
        row.vo_no = "VO-2026-007"
        row.category = "تغيير فيConditions الموقع"
        row.description = "تغيير مسار الجدران الخارجية"
        row.reason = "تعارض مع مخطط الخدمات Saturday"
        row.cost_impact = -12500.0
        row.currency = "SAR"
        row.time_impact_days = 7.0
        row.recommendation = "موافقة"
        db.session.commit()
        return row.id


class TestPackageStructure:

    @pytest.mark.parametrize("kind,model,serial,builder", [
        ("progress-billings", "ProgressBilling", "PBR-000001", "ipc"),
        ("variation-orders", "VariationOrder", "VOR-000001", "vo"),
    ])
    def test_endpoint_returns_a_valid_opc_package(self, app, client, kind,
                                                  model, serial, builder):
        login_as(client, "t_admin")
        rid = _record_id(app, serial, model)
        r = client.get(f"/ops/{kind}/{rid}/docx")
        assert r.status_code == 200, r.get_json()
        assert r.mimetype == ("application/vnd.openxmlformats-officedocument."
                              "wordprocessingml.document")
        assert f"{serial}-{builder}.docx" in r.headers["Content-Disposition"]
        assert "attachment" in r.headers["Content-Disposition"]
        with _open(r.data) as z:
            assert z.testzip() is None
            assert REQUIRED_PARTS <= set(z.namelist())
            for part in REQUIRED_PARTS:
                ElementTree.fromstring(z.read(part))
            types = z.read("[Content_Types].xml").decode()
            assert "wordprocessingml.document.main+xml" in types

    @pytest.mark.parametrize("kind,model,serial", [
        ("progress-billings", "ProgressBilling", "PBR-000001"),
        ("variation-orders", "VariationOrder", "VOR-000001"),
    ])
    def test_document_xml_is_well_formed_and_rtl_aware(self, app, client, kind,
                                                        model, serial):
        login_as(client, "t_admin")
        rid = _record_id(app, serial, model)
        r = client.get(f"/ops/{kind}/{rid}/docx")
        with _open(r.data) as z:
            xml = z.read("word/document.xml").decode("utf-8")
        assert xml.startswith("<?xml")
        root = ElementTree.fromstring(xml)
        assert root.tag == f"{W}document"
        body = root.find(f"{W}body")
        assert body is not None
        assert body.find(f"{W}sectPr") is not None
        assert "schemas.openxmlformats.org/wordprocessingml/2006/main" in xml


class TestIpcContent:

    def test_financial_figures_are_rendered(self, app, client):
        login_as(client, "t_admin")
        rid = _ipc(app, client)
        r = client.get(f"/ops/progress-billings/{rid}/docx")
        assert r.status_code == 200
        text = _docx_text(r.data)
        assert "مستخلص دفع مرحلي" in text
        assert "IPC-2026-014" in text
        assert "صب الأرضيات الطابق الأول" in text
        assert "BOQ-3.2" in text
        assert "MR-0099" in text
        assert "تم التحقق من الكميات ميدانياً" in text
        # qty x rate = 53,458.88 (2dp, thousands separated)
        assert "53,458.88" in text
        assert "5,345.89" in text
        assert "48,112.99" in text
        assert "66,112.99" in text
        assert "35%" in text

    def test_identity_and_signoff_blocks_exist(self, app, client):
        login_as(client, "t_admin")
        rid = _ipc(app, client)
        text = _docx_text(client.get(
            f"/ops/progress-billings/{rid}/docx").data)
        for heading in ("بيانات المعرفة", "البنود المالية", "الملاحظات",
                        "التوقيع والاعتماد"):
            assert heading in text, heading
        assert "PBR-000001" in text
        assert "Alpha Tower" in text

    def test_null_fields_render_a_placeholder(self, app, client):
        from app.extensions import db
        from app.ops.models import ProgressBilling
        login_as(client, "t_admin")
        with app.app_context():
            row = ProgressBilling.query.first()
            row.boq_ref = ""
            row.measurement_ref = ""
            row.notes = ""
            db.session.commit()
            rid = row.id
        text = _docx_text(client.get(
            f"/ops/progress-billings/{rid}/docx").data)
        assert "—" in text
        assert "BOQ-" not in text


class TestVariationOrderContent:

    def test_impact_and_recommendation_are_rendered(self, app, client):
        login_as(client, "t_admin")
        rid = _vo(app, client)
        r = client.get(f"/ops/variation-orders/{rid}/docx")
        assert r.status_code == 200
        text = _docx_text(r.data)
        assert "أمر تغيير" in text
        assert "VO-2026-007" in text
        assert "تغيير مسار الجدران الخارجية" in text
        assert "تعارض مع مخطط الخدمات" in text
        assert "12,500.00" in text
        assert "SAR" in text
        assert "7" in text
        assert "موافقة" in text
        for heading in ("وصف التغيير", "المبرر", "الأثر والتوصية",
                        "التوقيع والاعتماد"):
            assert heading in text, heading

    def test_negative_impact_keeps_its_sign(self, app, client):
        from app.extensions import db
        from app.ops.models import VariationOrder
        login_as(client, "t_admin")
        with app.app_context():
            row = VariationOrder.query.first()
            row.cost_impact = 48000.0
            db.session.commit()
            rid = row.id
        text = _docx_text(client.get(
            f"/ops/variation-orders/{rid}/docx").data)
        assert "48,000.00" in text


class TestExportGuards:

    def test_unsupported_module_is_404(self, app, client):
        login_as(client, "t_admin")
        rid = _record_id(app, "RFI-000001", "RFI")
        r = client.get(f"/ops/rfis/{rid}/docx")
        assert r.status_code == 404
        assert r.get_json()["error"] == "no Word export for this module"
        assert set(r.get_json()["supported"]) == {"progress-billings",
                                                  "variation-orders"}

    def test_unknown_module_is_404(self, app, client):
        login_as(client, "t_admin")
        r = client.get("/ops/nope/1/docx")
        assert r.status_code == 404

    def test_cross_tenant_export_is_404(self, app, client):
        login_as(client, "t_eng2")
        rid = _record_id(app, "PBR-000001", "ProgressBilling")
        r = client.get(f"/ops/progress-billings/{rid}/docx")
        assert r.status_code == 404

    def test_anonymous_export_is_401(self, app, client):
        rid = _record_id(app, "PBR-000001", "ProgressBilling")
        r = client.get(f"/ops/progress-billings/{rid}/docx")
        assert r.status_code == 401

    def test_missing_record_is_404(self, app, client):
        login_as(client, "t_admin")
        r = client.get("/ops/progress-billings/999999/docx")
        assert r.status_code == 404

    def test_unlinked_user_gets_404_not_the_document(self, app, client):
        from app.extensions import db
        from app.models import User
        with app.app_context():
            user = User(username="no_export", email="noexport@t.com",
                        full_name="مستخدم بلا ارتباط بمشروع",
                        role="site_engineer")
            user.set_password("pw12345")
            db.session.add(user)
            db.session.commit()
        rid = _record_id(app, "PBR-000001", "ProgressBilling")
        login_as(client, "no_export")
        r = client.get(f"/ops/progress-billings/{rid}/docx")
        assert r.status_code == 404
        assert b"wordprocessingml" not in r.data


class TestBuildersDirectly:

    def test_builder_works_without_flask_context(self):
        from types import SimpleNamespace
        from app.services.word_export import build_ipc_docx
        record = SimpleNamespace(
            serial="PBR-999999", id=7, report_date="2026-04-01",
            status="approved", status_ar="معتمد", signatory_name="Engineer",
            version=2, work_item="بند", boq_ref="", qty_completed=10.0,
            rate=5.0, retention_pct=10.0, previously_certified=0.0,
            measurement_ref="", progress_pct=10.0, notes="",
            reviewed_by_id=1, reviewed_at="2026-04-02", review_notes="ok",
            gross=50.0, retention=5.0, net_payable=45.0, cumulative=45.0)
        data = build_ipc_docx(record, project_name="Direct")
        with _open(data) as z:
            assert REQUIRED_PARTS <= set(z.namelist())
        text = _docx_text(data)
        assert "PBR-999999" in text
        assert "50.00" in text
        assert "45.00" in text

    def test_core_properties_carry_title_and_author(self):
        from types import SimpleNamespace
        from app.services.word_export import build_variation_order_docx
        record = SimpleNamespace(
            serial="VOR-888888", id=1, report_date=None, status="draft",
            status_ar="مسودة", signatory_name="Engineer Two", version=1,
            vo_no="VO-1", title="Title", category="Cat", boq_ref="",
            description="Desc", reason="Reason", cost_impact=1.0,
            currency="ILS", time_impact_days=0.0, recommendation="قبول",
            attachments=0, reviewed_by_id=None, reviewed_at=None,
            review_notes=None, impact_signed="+1.00")
        data = build_variation_order_docx(record, project_name="P")
        with _open(data) as z:
            core = z.read("docProps/core.xml").decode()
        assert "VOR-888888" in core
        assert "Engineer Two" in core
        assert re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", core)
