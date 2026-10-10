# Employee Attendance & Analytics API

![Python](https://img.shields.io/badge/Python-3.14-blue?logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.143-green?logo=fastapi)
![MongoDB](https://img.shields.io/badge/MongoDB-7.0-green?logo=mongodb)
![PyMongo](https://img.shields.io/badge/PyMongo-4.18-orange)
![Pydantic](https://img.shields.io/badge/Pydantic-2.14-red)

A FastAPI-based REST API for employee attendance tracking with automated business rules, manual corrections with audit trails, and analytics powered by MongoDB aggregations.

## Features

- Employee management with shift scheduling (supports overnight shifts)
- Punch-in/punch-out with automatic late/overtime calculation
- Attendance regularization with complete audit trail
- Monthly employee and department analytics
- Late-comers leaderboard with competition ranking
- Daily attendance trends with 7-day moving averages

## Tech Stack

- **Python 3.14**: Core programming language
- **FastAPI 0.143**: Web framework
- **MongoDB 7.0**: Database
- **PyMongo 4.18**: MongoDB driver
- **Pydantic 2.14**: Data validation

## Installation

```bash
python -m venv .venv
.venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

Set environment variables in `.env`:
```env
MONGO_URI=mongodb://localhost:27017
MONGO_DB=attendance_db
```

## Running

```bash
uvicorn app.main:app --port 8000
```

API available at `http://localhost:8000` with docs at `/docs`

## API Endpoints

- `GET /health` - Health check
- `POST /employees` - Create employee
- `GET /employees` - List employees
- `POST /attendance/punch-in` - Record punch-in
- `POST /attendance/punch-out` - Record punch-out
- `GET /attendance` - List attendance
- `PATCH /attendance/{emp_code}/{date}` - Regularize attendance
- `GET /analytics/employees/{emp_code}/monthly` - Employee monthly summary
- `GET /analytics/departments/summary` - Department summary
- `GET /analytics/leaderboard/late` - Late-comers leaderboard
- `GET /analytics/departments/{department}/trend` - Department trend
- `GET /admin/explain/{endpoint}` - Query explain

## Implementation Notes

- All code in `app/main.py`
- MongoDB indexes created at startup
- IST timezone handling (UTC+05:30)
- Business rules R1-R10 implemented
- Concurrency-safe via database constraints
