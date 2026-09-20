with open('.github/workflows/ci.yml', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace broken version pin with exact working version
content = content.replace('click==8.5.0', 'click==8.4.2')

# Make verification a HARD GATE: if click version is not exactly 8.4.2, fail
old_check = 'python -c "import click; print(\'click verified:\', click.__version__)"'
new_check = 'python -c "import click; ver = click.__version__; assert ver == \'8.4.2\', f\'FAIL: click={ver}, expected 8.4.2\'; print(f\'PASS: click verified exactly 8.4.2\')"'
content = content.replace(old_check, new_check)

with open('.github/workflows/ci.yml', 'w', encoding='utf-8') as f:
    f.write(content)
print('Fixed: exact 8.4.2 with HARD GATE')
