# 🏗️ Construction Management & Dynamic Reporting SaaS Platform
### منصة إدارة المشاريع والتقارير الديناميكية — Mobile-First • RTL • Arabic PDF

Modular, cloud-native SaaS: **platform owners** design report templates with a
**dynamic form builder**, **field engineers** fill them on smartphones, and the
system stamps their **Full Four-Part Name (الاسم الرباعي)** + timestamp into
the DB record and the official A4 PDF.

## ✨ Key capabilities
- **Dynamic Form Builder** — owners create templates (Daily/Weekly/Monthly/
  Safety/Variation…) and add/edit/remove/reorder fields
  (`text, textarea, number, dropdown, date, checkbox`) with required flags —
  no code changes, live instantly in field forms + PDFs.
- **Multi-tier RBAC** — `superadmin` (platform owner) / `admin` /
  `project_manager` / `safety_officer` / `site_engineer`
  (legacy `user`/`admin` rows keep working).
- **Auto-Sign & Audit Trail** — every submission binds `user_id`,
  `signatory_name` snapshot, `created_at/updated_at`.
- **Arabic RTL PDF engine** — ReportLab + arabic-reshaper + python-bidi,
  Amiri font auto-downloaded to `./fonts` (Helvetica fallback offline).
  One generic renderer serves *any* dynamic template + legacy static layouts.
- **Anti-duplicate** — unique `(template, project, date)` and legacy
  `(project, type, date)` enforced in app + DB.
- **Analytics** — submissions/day chart + per-template breakdown.
- **Mobile-first RTL UI** — Tailwind CDN, bottom nav, 16px inputs,
  auto-growing textareas.

## 🗂️ Modular structure (spec layout)
```
app/
  __init__.py          # Flask factory: registers blueprints, Migrate, CLI
  extensions.py        # db / login_manager / migrate singletons
  models.py            # User, Project, ReportTemplate, DynamicField,
                       #   ReportSubmission (+ legacy Report)
  auth/                # login / register / logout (tiered roles)
  admin/               # owner dashboard, template builder, field manager,
                       #   projects, users (roles/suspend/delete), analytics
  reports/             # LEGACY static CRUD + DYNAMIC SaaS CRUD + PDFs
  main/                # landing, dashboard selector, combined archive, profile
  services/
    pdf_dynamic.py     # generic A4 renderer for any template
    default_templates.py  # 5 default templates + field schema + seeder
  utils/decorators.py  # roles_required / admin_required / superadmin_required
templates/  static/  fonts/  instance/
app.py                 # thin entry (gunicorn app:app)
config.py              # SQLite local / Postgres cloud (stray-DATABASE_URL safe)
requirements.txt  seed.py  Procfile  render.yaml  Dockerfile
```

## 🚀 Local setup
```bash
python -m venv venv
# Windows: venv\Scripts\activate | Linux/macOS: source venv/bin/activate
pip install -r requirements.txt
python seed.py
python app.py            # → http://127.0.0.1:5000
```

## 🗄️ Database & migrations (Flask-Migrate)
`db.create_all()` runs on boot (dev convenience). For controlled schema
evolution:
```bash
python -m flask --app app db init        # once: creates migrations/
python -m flask --app app db migrate -m "describe change"
python -m flask --app app db upgrade
python -m flask --app app seed           # demo accounts
python -m flask --app app seed-demo-reports
```
Cloud Postgres is used **only** when opted in
(`USE_CLOUD_DB=1`, `FLASK_ENV=production`, Render/Railway markers, or a local
`.env` with `DATABASE_URL`) — a stray global `DATABASE_URL` on a dev machine
is ignored and SQLite is used instead.

## ☁️ Deployment (Render / Railway / Heroku / Docker)
- Build: `pip install -r requirements.txt`
- Start: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120`
- Env: `SECRET_KEY=<random>` · `DATABASE_URL=<postgres url>` ·
  `USE_CLOUD_DB=1` · then `flask --app app db upgrade` once.
- First registered account becomes **superadmin** automatically.

## 🧪 Demo accounts (after `python seed.py`)
| Role | Username | Password |
|---|---|---|
| Platform Owner | `owner` | `owner123` |
| Project Manager/Admin | `admin` | `admin123` |
| Site Engineer | `engineer` | `site123` |
| Safety Officer | `safety` | `safe123` |

## 🏭 Azadexa operational modules (production-grade)
Six first-class tables under `app/ops/` with serials, approval workflow
(`pending → approved/rejected` + reviewer stamp), and composite indexes:
`site_inspections` (SIR: concrete/soil/MEP + auto pass/fail),
`material_submittals` (MSR), `rfis` (RFI + days-open),
`cost_variances` (CVR: budgeted/actual/re-estimate + variance %),
`progress_billings` (PBR: gross − retention = net + cumulative),
`subcontractor_performances` (SPR: weighted score + grade A–D).
- **Tenant isolation (fail-closed RLS)**: `project_members` grants; managers
  bypass globally; everyone else sees only member projects. Cross-tenant
  object access returns **404** (no IDOR oracle); role-denied actions 403.
- **Endpoints**: `GET /ops/` (registry), CRUD per
  `/ops/<module>`, `POST …/approve`, `GET …/pdf` (serial filename, status
  watermark, approval block), `GET /ops/api/archive` (filter by type/project/
  status/date/search + sort + pagination).
- **Migrations**: `migrations/versions/ed9ec77b7fc2_…py` (upgrade/downgrade
  verified). Set `AZADEXA_AUTO_CREATE=0` for pure Alembic diffs.
- **Tests**: `python -m pytest tests` — 35 tests (RBAC, financial accuracy,
  CRUD integrity, isolation/IDOR, PDF + archive).

## 🔒 Pre-production checklist
- [ ] Strong `SECRET_KEY`, `DEBUG=False` (gunicorn path already is)
- [ ] HTTPS via host, Postgres backups, `db upgrade` in release phase
