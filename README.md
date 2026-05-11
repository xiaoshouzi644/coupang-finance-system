# Coupang Finance System

A Streamlit-based finance reconciliation and auditing system for e-commerce operations.

## Overview

This project contains the source code for the finance system currently used behind `/finance/`.
It is designed to help with financial reconciliation, auditing workflows, and operational checks.

## Tech Stack

- Python
- Streamlit
- Nginx reverse proxy (deployment-side)

## Run Locally

Install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Start the app:

```bash
streamlit run app.py --server.port 8501 --server.address 127.0.0.1
```

If you want the same path behavior as production, you can run with:

```bash
streamlit run app.py --server.port 8501 --server.address 127.0.0.1 --server.baseUrlPath finance
```

## Regression Check

Run the regression check script:

```bash
.venv/bin/python tools/regression_check.py
```

The output includes:

- `structure`: field recognition results
- `behavior`: numeric-column pass rate and key field completeness
- `verdict`: whether the minimum regression gate passed

Current built-in sample directory:

```text
/opt/shuju
```

## Backup and Rollback

Create a backup:

```bash
bash tools/create_backup.sh
```

Rollback to a specific backup:

```bash
bash tools/rollback.sh backup-YYYYMMDD-HHMMSS
```

## Project Structure

```text
.
├── app.py
├── requirements.txt
├── VERSION.txt
├── tools/
│   ├── create_backup.sh
│   ├── regression_check.py
│   └── rollback.sh
└── README.md
```

## Notes

- Python virtual environments such as `.venv/` are intentionally excluded from version control.
- Temporary caches and compiled Python files are also excluded.
- Local backup artifacts should not be committed to the repository.
