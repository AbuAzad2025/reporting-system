import urllib.request, json, sys

packages = {
    'Flask': None,
    'click': None,
    'Flask-SQLAlchemy': None,
    'Flask-Login': None,
    'Flask-Migrate': None,
    'Werkzeug': None,
    'reportlab': None,
    'pytest': None,
    'pytest-cov': None,
    'psycopg2-binary': None,
    'gunicorn': None,
    'flake8': None,
}

for pkg in packages:
    try:
        url = f'https://pypi.org/pypi/{pkg}/json'
        data = json.loads(urllib.request.urlopen(url, timeout=5).read())
        latest = data['info']['version']
        print(f'{pkg}: latest={latest}')
    except Exception as e:
        print(f'{pkg}: check failed ({e})')
