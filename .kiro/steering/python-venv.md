---
inclusion: fileMatch
fileMatchPattern: "**/*.py,requirements.txt,setup.py,pyproject.toml"
---

## Python Virtual Environment

All Python commands must use the venv at `venv/` (workspace root). Never use system `python` or `pip`.

```bash
venv/bin/python <script>
venv/bin/pip install <package>
venv/bin/uvicorn app.api.main:app --reload
venv/bin/pytest <path>
```

Python 3.10+ required.
