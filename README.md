# Employee Attendance & Analytics API

A REST API built with **Python**, **FastAPI**, and **MongoDB** for employee attendance operations and attendance analytics.

## Features

- Employee and attendance API routes defined in `app/main.py`.
- Punch-in and punch-out handling with attendance validation.
- Attendance correction history for traceability.
- Attendance analytics endpoints.
- MongoDB indexes, including a unique index on `emp_code` and `date` to prevent duplicate daily attendance records.
- Interactive API documentation through Swagger UI.

> **Implementation status:** The current local test suite contains six attendance-calculation tests. They pass, but they do not verify every API contract or analytics edge case. See `REVIEW.md` for reviewed items and remaining verification work; see `DECISIONS.md` for design choices.

## Requirements

- Python 3.12 (the project was tested with Python 3.12)
- MongoDB local instance or a MongoDB connection URI
- Git

## Setup

1. Clone the repository and enter the project directory:

   ```bash
   git clone https://github.com/Maximilina02/employee-attendance-analytics-api.git
   cd employee-attendance-analytics-api
   ```

2. Create and activate a virtual environment.

   **Windows (Git Bash):**

   ```bash
   python -m venv .venv
   source .venv/Scripts/activate
   ```

   **Windows (PowerShell):**

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. Install dependencies:

   ```bash
   python -m pip install -r requirements.txt
   ```

4. Configure MongoDB. The application reads these environment variables:

   - `MONGO_URI` — MongoDB connection URI. Defaults to `mongodb://localhost:27017`.
   - `MONGO_DB` — database name. Defaults to `attendance_db`.

   For a local MongoDB instance, the defaults can be used. For MongoDB Atlas, set `MONGO_URI` and `MONGO_DB` in your local environment or an ignored `.env` file. **Do not commit credentials, connection strings, or `.env` files.**

## Run the API

From the repository root, run:

```bash
python -m uvicorn app.main:app --reload --port 8000
```

Open:

- Swagger UI: <http://127.0.0.1:8000/docs>
- ReDoc: <http://127.0.0.1:8000/redoc>
- Health endpoint: <http://127.0.0.1:8000/health>

The API requires a reachable MongoDB server for database-backed operations. Check your MongoDB connection and environment variables if those operations fail.

## Run tests

```bash
python -m pytest -q
```

The current included tests cover selected attendance calculation boundaries, including late-grace-period, work-hours, half-day, and overtime rules. Passing these tests does not establish that all endpoint contracts, MongoDB aggregation requirements, concurrency cases, and audit requirements are fully verified.

## Repository guide

- `app/main.py` — API implementation
- `openapi.yaml` — API contract and business rules
- `DATA_MODEL.md` — MongoDB data model notes
- `sample_data/` — sample MongoDB Extended JSON documents
- `sample_seed.py` — loads sample data
- `tests/` — automated tests
- `REVIEW.md` — code review findings and verification notes
- `DECISIONS.md` — design decisions and trade-offs

## Known limitations

Refer to `REVIEW.md` for the current findings and remaining verification items. Do not assume that every analytics requirement is complete solely because the included calculation tests pass.
