with open('.github/workflows/ci.yml', 'r', encoding='utf-8') as f:
    content = f.read()

old_text = "        run: |\n          python -m pip install --upgrade pip\n          pip install click==8.2.1\n          pip install -r requirements.txt pytest pytest-cov flake8 click==8.2.1"
new_text = "        run: |\n          python -m pip install --upgrade pip --no-cache-dir\n          python -m pip install --force-reinstall --no-cache-dir click==8.2.1\n          python -c \"import click; print('click verified:', click.__version__)\"\n          pip install -r requirements.txt pytest pytest-cov flake8"

content = content.replace(old_text, new_text)

with open('.github/workflows/ci.yml', 'w', encoding='utf-8') as f:
    f.write(content)
print('Fixed bulletproof click')
