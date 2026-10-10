# Employee Attendance & Analytics API

![Python](https://img.shields.io/badge/Python-3.14-blue?logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.143-green?logo=fastapi)
![MongoDB](https://img.shields.io/badge/MongoDB-7.0-green?logo=mongodb)
![PyMongo](https://img.shields.io/badge/PyMongo-4.18-orange)
![Pydantic](https://img.shields.io/badge/Pydantic-2.14-red)

A comprehensive FastAPI-based REST API for tracking employee attendance with automated business rule calculations, manual corrections with audit trails, and advanced analytics powered by MongoDB aggregation pipelines.

## Project Overview

This API provides a complete attendance management system that handles:
- Employee management with configurable shift schedules
- Automated punch-in/punch-out tracking with late detection and overtime calculation
- Manual attendance corrections with full audit trail tracking
- Multi-level analytics (employee, department, organization-wide)
- Real-time leaderboards and trend analysis

## Features

### Core Functionality
- **Employee Management**: Create and manage employees with customizable shift timings (supports overnight shifts)
- **Punch-in/Punch-out**: Automated attendance recording with real-time validation
- **Business Rules**: Automatic calculation of late minutes, overtime, work hours, and half-day status
- **Regularization**: Manual corrections with complete audit trail tracking
- **Status Management**: Support for PRESENT, WFH, ON_DUTY, ABSENT, and LEAVE statuses

### Analytics
- **Employee Monthly Summary**: Individual attendance metrics including working days, present days, leave days, late count, and attendance percentage
- **Department Summary**: Aggregated department-level statistics with headcount, average work hours, and presence metrics
- **Late-comers Leaderboard**: Competition ranking of employees by total late minutes
- **Department Trend**: Daily attendance trends with 7-day moving averages and attendance rates

### Advanced Features
- **IST Timezone Support**: All calculations use Indian Standard Time (UTC+05:30)
- **Overnight Shift Handling**: Correct date calculation for shifts spanning midnight
- **Concurrency Safety**: Database-level constraints prevent duplicate entries
- **Performance Optimized**: MongoDB indexes ensure fast queries on large datasets
- **Audit Trail**: Complete history of all manual corrections with before/after values

## Tech Stack

- **Python 3.14**: Core programming language
- **FastAPI 0.143**: Modern, fast web framework for building APIs
- **MongoDB 7.0**: NoSQL database for flexible data storage
- **PyMongo 4.18**: MongoDB driver for Python
- **Pydantic 2.14**: Data validation using Python type annotations
- **Uvicorn**: ASGI server for running FastAPI applications

## Business Rules (R1-R10)

The API implements the following business rules:

- **R1**: IST timezone handling with overnight shift support and second truncation
- **R2**: Late detection with 10-minute grace period (strictly >10:00 counts as late)
- **R3**: Overtime calculation with 30-minute minimum threshold
- **R4**: Work hours rounded to 2 decimals using half-up rounding
- **R5**: Half-day detection when work hours < 4.50
- **R6**: Presence status (PRESENT, WFH, ON_DUTY count as present)
- **R7**: Working days are Mon-Fri, counted from employee's joined_on date
- **R8**: Reported numbers rounded to 2 decimals (4 decimals for rates)
- **R9**: Headcount includes employees with zero attendance logs
- **R10**: Pagination with page starting at 1, max page_size of 100

## API Endpoints

### System
- `GET /health` - Health check (returns 200 if MongoDB is available, 503 otherwise)

### Employees
- `POST /employees` - Create a new employee
- `GET /employees` - List employees with pagination and department filter

### Attendance
- `POST /attendance/punch-in` - Record a punch-in
- `POST /attendance/punch-out` - Record a punch-out
- `GET /attendance` - List attendance records with filters
- `PATCH /attendance/{emp_code}/{date}` - Regularize (manually correct) attendance

### Analytics
- `GET /analytics/employees/{emp_code}/monthly` - Monthly employee summary
- `GET /analytics/departments/summary` - Department monthly summary
- `GET /analytics/leaderboard/late` - Late-comers leaderboard
- `GET /analytics/departments/{department}/trend` - Daily department trend

### Admin
- `GET /admin/explain/{endpoint}` - MongoDB query explain for performance analysis

## Installation

### Prerequisites
- Python 3.11 or higher
- MongoDB 6.0 or higher (local Docker or MongoDB Atlas)
- Git

### Setup Steps

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd Employee-Attendance-Analytics-API
   ```

2. **Create virtual environment**
   ```bash
   python -m venv .venv
   .venv\Scripts\activate  # Windows
   # or
   source .venv/bin/activate  # Linux/Mac
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up MongoDB**
   
   **Option A: Docker (Recommended for development)**
   ```bash
   docker run -d -p 27017:27017 --name attendance-mongo mongo:7
   ```
   
   **Option B: MongoDB Atlas**
   - Create a free M0 cluster at https://www.mongodb.com/cloud/atlas
   - Get your connection string
   - Whitelist your IP address in Network Access

5. **Configure environment variables**
   
   Create a `.env` file in the project root:
   ```env
   MONGO_URI=mongodb://localhost:27017
   # or for Atlas:
   # MONGO_URI=mongodb+srv://<username>:<password>@cluster.mongodb.net/?retryWrites=true&w=majority
   MONGO_DB=attendance_db
   ```

6. **Load sample data** (optional)
   ```bash
   python sample_seed.py
   ```

## Running the Application

Start the server:
```bash
uvicorn app.main:app --port 8000
```

For development with auto-reload:
```bash
uvicorn app.main:app --port 8000 --reload
```

The API will be available at `http://localhost:8000`

Interactive API documentation (Swagger UI) is available at:
- `http://localhost:8000/docs`

## Testing

### Health Check
```bash
curl http://localhost:8000/health
```

### Create Employee
```bash
curl -X POST http://localhost:8000/employees \
  -H "Content-Type: application/json" \
  -d '{
    "emp_code": "EMP0001",
    "name": "John Doe",
    "email": "john@example.com",
    "department": "Engineering",
    "shift_start": "09:30",
    "shift_end": "18:30",
    "joined_on": "2026-01-05"
  }'
```

### Punch-in
```bash
curl -X POST http://localhost:8000/attendance/punch-in \
  -H "Content-Type: application/json" \
  -d '{"emp_code": "EMP0001", "status": "PRESENT"}'
```

### Get Analytics
```bash
curl "http://localhost:8000/analytics/employees/EMP0001/monthly?month=2026-07"
```

## Project Structure

```
Employee-Attendance-Analytics-API/
├── app/
│   └── main.py              # Complete API implementation (1335 lines)
├── sample_data/              # Sample MongoDB documents
│   ├── employees.json
│   └── attendance_logs.json
├── .gitignore                # Git ignore rules
├── DATA_MODEL.md            # MongoDB data model specification
├── DECISIONS.md            # Technical design decisions
├── PROBLEM_STATEMENT.docx  # Original problem statement
├── README.md                # This file
├── REVIEW.md                # Code review findings (36 bugs)
├── openapi.yaml             # OpenAPI specification
├── requirements.txt         # Python dependencies
└── sample_seed.py          # Script to load sample data
```

## Implementation Details

### MongoDB Indexes
The following indexes are created at startup for optimal performance:
- `employees.emp_code` (unique) - Ensures employee code uniqueness
- `attendance_logs.{emp_code, date}` (unique) - Prevents duplicate attendance records
- `attendance_logs.date` (descending) - Optimizes date range queries
- `attendance_logs.status` - Optimizes status filtering
- `attendance_logs.{date, status}` - Compound index for analytics

### Concurrency Handling
- Database-level unique indexes prevent duplicate punch-ins
- Conditional updates prevent concurrent punch-out conflicts
- ACID guarantees ensure data consistency

### Data Model
- **employees**: Employee records with shift schedules
- **attendance_logs**: Attendance records with computed fields
- All timestamps stored as BSON dates in MongoDB, returned as epoch milliseconds in API
- Derived fields (late_minutes, work_hours, overtime_minutes, half_day) computed by API

### Performance Considerations
- All pagination handled at database level (skip/limit)
- Sorting performed by MongoDB, not in application
- Aggregation pipelines used for analytics
- Indexes ensure IXSCAN instead of COLLSCAN for filtered queries

## Configuration

### Environment Variables
- `MONGO_URI`: MongoDB connection string (required)
- `MONGO_DB`: Database name (defaults to `attendance_db`)

### Pydantic Validation
- Epoch milliseconds validated (rejects seconds-looking values < 100000000000)
- Employee code pattern: `EMP\d{4,6}`
- Email format validation
- Date format: `YYYY-MM-DD`
- Time format: `HH:MM` (24-hour)
- Pagination limits: page_size max 100

## Troubleshooting

### MongoDB Connection Issues
- Ensure MongoDB is running: `docker ps` or check Atlas cluster status
- Verify MONGO_URI in .env file
- Check network connectivity for Atlas (IP whitelisted)

### Import Errors
- Ensure virtual environment is activated
- Reinstall dependencies: `pip install -r requirements.txt`

### Port Already in Use
- Change port: `uvicorn app.main:app --port 8001`
- Or kill process using port 8000

## Documentation

- **OpenAPI Specification**: See `openapi.yaml` for complete API contract
- **Data Model**: See `DATA_MODEL.md` for MongoDB schema details
- **Business Rules**: See R1-R10 in `openapi.yaml` for detailed rule descriptions
- **Code Review**: See `REVIEW.md` for identified bugs in starter code
- **Design Decisions**: See `DECISIONS.md` for architectural decisions

## License

This project is submitted as part of a technical assessment.
