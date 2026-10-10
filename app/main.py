"""
Employee Attendance & Analytics API

Run:  uvicorn app.main:app --port 8000
Env:  MONGO_URI, MONGO_DB (a local .env is loaded for convenience)
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from decimal import Decimal, ROUND_HALF_UP

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError

load_dotenv()

client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
db = client[os.getenv("MONGO_DB", "attendance_db")]

IST = timezone(timedelta(hours=5, minutes=30))

app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
EPOCH_MIN = 100000000000  # Jan 1, 1973 (reject seconds-looking values)
EPOCH_MAX = 4102444800000  # Jan 1, 2100
GRACE_MINUTES = 10
OVERTIME_THRESHOLD_MINUTES = 30
HALF_DAY_HOURS = 4.50

STATUS_VALUES = ["PRESENT", "ABSENT", "LEAVE", "WFH", "ON_DUTY"]
PRESENCE_STATUS_VALUES = ["PRESENT", "WFH", "ON_DUTY"]


# --------------------------------------------------------------------------- #
# Helper Functions
# --------------------------------------------------------------------------- #
def epoch_to_datetime(epoch_ms: int) -> datetime:
    """Convert epoch milliseconds to UTC datetime."""
    return datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc)


def datetime_to_epoch(dt: datetime) -> int:
    """Convert datetime to epoch milliseconds."""
    return int(dt.timestamp() * 1000)


def to_ist(dt: datetime) -> datetime:
    """Convert UTC datetime to IST."""
    return dt.astimezone(IST)


def truncate_to_seconds(dt: datetime) -> datetime:
    """Truncate datetime to whole seconds (R1)."""
    return dt.replace(microsecond=0)


def calculate_attendance_date(punch_in_utc: datetime, shift_start: str, shift_end: str) -> str:
    """
    Calculate attendance date per R1.
    For overnight shifts (shift_end <= shift_start), a punch-in whose IST time
    is earlier than shift_end belongs to the previous day's shift.
    """
    punch_in_ist = to_ist(punch_in_utc)
    h, m = map(int, shift_start.split(":"))
    shift_start_dt = punch_in_ist.replace(hour=h, minute=m, second=0, microsecond=0)
    
    h_end, m_end = map(int, shift_end.split(":"))
    shift_end_dt = punch_in_ist.replace(hour=h_end, minute=m_end, second=0, microsecond=0)
    
    # Check if overnight shift
    if shift_end_dt <= shift_start_dt:
        # Overnight shift: if punch_in is before shift_end, it belongs to previous day
        if punch_in_ist < shift_end_dt:
            return (punch_in_ist - timedelta(days=1)).date().isoformat()
    
    return punch_in_ist.date().isoformat()


def calculate_shift_end_datetime(attendance_date: str, shift_end: str) -> datetime:
    """
    Calculate the shift end datetime for a given attendance date.
    Handles overnight shifts (shift_end <= shift_start).
    """
    h, m = map(int, shift_end.split(":"))
    date_dt = datetime.fromisoformat(attendance_date)
    shift_end_dt = date_dt.replace(hour=h, minute=m, second=0, microsecond=0, tzinfo=IST)
    
    # If shift_end is "before" shift_start (e.g., 06:00 after 22:00), it's overnight
    # So shift_end is actually on the next day
    # We need to know shift_start to determine this, but for simplicity:
    # If the time is "early" (before 12:00), assume it's the next day
    if h < 12:
        shift_end_dt = shift_end_dt + timedelta(days=1)
    
    return shift_end_dt


def compute_late_minutes(punch_in_utc: datetime, shift_start: str) -> int:
    """
    Compute late minutes per R2.
    Grace period is 10 minutes. Late only if strictly more than 10:00 after shift_start.
    Late minutes = whole minutes (floor) elapsed since shift_start.
    """
    punch_in_ist = to_ist(punch_in_utc)
    h, m = map(int, shift_start.split(":"))
    shift_start_dt = punch_in_ist.replace(hour=h, minute=m, second=0, microsecond=0)
    
    delta = punch_in_ist - shift_start_dt
    minutes = int(delta.total_seconds() / 60)
    
    # Only count if strictly more than 10 minutes late
    if minutes > GRACE_MINUTES:
        return minutes
    return 0


def compute_work_hours(punch_in_utc: datetime, punch_out_utc: datetime) -> float:
    """
    Compute work hours per R4.
    (punch_out - punch_in) in seconds / 3600, rounded to 2 decimals half-up.
    """
    # Ensure both are timezone-aware
    if punch_in_utc.tzinfo is None:
        punch_in_utc = punch_in_utc.replace(tzinfo=timezone.utc)
    if punch_out_utc.tzinfo is None:
        punch_out_utc = punch_out_utc.replace(tzinfo=timezone.utc)
    
    seconds = (punch_out_utc - punch_in_utc).total_seconds()
    hours = Decimal(seconds) / Decimal(3600)
    # Round to 2 decimals, half-up
    rounded = hours.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return float(rounded)


def compute_overtime_minutes(punch_out_utc: datetime, shift_end: str, attendance_date: str) -> int:
    """
    Compute overtime minutes per R3.
    Whole minutes (floor) between shift_end and punch_out, counted only when >= 30.
    """
    shift_end_dt = calculate_shift_end_datetime(attendance_date, shift_end)
    # Ensure punch_out is timezone-aware
    if punch_out_utc.tzinfo is None:
        punch_out_utc = punch_out_utc.replace(tzinfo=timezone.utc)
    punch_out_ist = to_ist(punch_out_utc)
    
    delta = punch_out_ist - shift_end_dt
    minutes = int(delta.total_seconds() / 60)
    
    # Only count if >= 30 minutes
    if minutes >= OVERTIME_THRESHOLD_MINUTES:
        return minutes
    return 0


def compute_half_day(work_hours: float) -> bool:
    """
    Compute half_day per R5.
    True when rounded work_hours < 4.50.
    """
    return work_hours < HALF_DAY_HOURS


def is_working_day(date_str: str) -> bool:
    """Check if a date is a working day (Mon-Fri)."""
    dt = datetime.fromisoformat(date_str)
    return dt.weekday() < 5  # 0=Mon, 4=Fri


def round_half_up(value: float, decimals: int = 2) -> float:
    """Round a float to specified decimals using half-up rounding (R8)."""
    multiplier = 10 ** decimals
    rounded = (Decimal(str(value)) * Decimal(multiplier)).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
    return float(rounded / Decimal(multiplier))


# --------------------------------------------------------------------------- #
# Pydantic Models
# --------------------------------------------------------------------------- #
class EmployeeCreate(BaseModel):
    emp_code: str = Field(..., pattern=r'^EMP\d{4,6}$')
    name: str = Field(..., min_length=1, max_length=100)
    email: str = Field(..., max_length=120, pattern=r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
    department: str = Field(..., min_length=1, max_length=50)
    shift_start: str = Field(default="09:30", pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    shift_end: str = Field(default="18:30", pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    joined_on: str = Field(..., format='date')
    
    @field_validator('shift_end')
    @classmethod
    def shift_times_must_differ(cls, v, info):
        if 'shift_start' in info.data and v == info.data['shift_start']:
            raise ValueError('shift_end must differ from shift_start')
        return v


class Employee(BaseModel):
    emp_code: str
    name: str
    email: str
    department: str
    shift_start: str
    shift_end: str
    joined_on: str
    created_at: int  # epoch milliseconds


class EmployeePage(BaseModel):
    items: List[Employee]
    total: int
    page: int
    page_size: int


class PunchInRequest(BaseModel):
    emp_code: str
    punched_at: Optional[int] = Field(None, ge=EPOCH_MIN, le=EPOCH_MAX)
    status: str = Field(default="PRESENT")


class PunchOutRequest(BaseModel):
    emp_code: str
    punched_at: Optional[int] = Field(None, ge=EPOCH_MIN, le=EPOCH_MAX)


class RegularizeRequest(BaseModel):
    status: Optional[str] = None
    punch_in: Optional[int] = Field(None, ge=EPOCH_MIN, le=EPOCH_MAX)
    punch_out: Optional[int] = Field(None, ge=EPOCH_MIN, le=EPOCH_MAX)
    reason: str = Field(..., min_length=5, max_length=200)
    regularized_by: str = Field(..., min_length=1, max_length=50)


class HistoryEntry(BaseModel):
    at: int
    by: str
    reason: str
    changes: dict


class AttendanceRecord(BaseModel):
    emp_code: str
    date: str
    status: str
    punch_in: Optional[int]
    punch_out: Optional[int]
    work_hours: Optional[float]
    late_minutes: int
    overtime_minutes: int
    half_day: bool = False
    history: List[HistoryEntry] = []


class AttendancePage(BaseModel):
    items: List[AttendanceRecord]
    total: int
    page: int
    page_size: int


class EmployeeMonthly(BaseModel):
    emp_code: str
    month: str
    working_days: int
    present_days: float
    leave_days: int
    late_count: int
    total_late_minutes: int
    total_overtime_minutes: int
    attendance_pct: Optional[float]


class DepartmentSummaryItem(BaseModel):
    department: str
    headcount: int
    present_days: float
    avg_work_hours: Optional[float]
    late_count: int
    total_late_minutes: int
    leave_count: int
    on_duty_count: int


class DepartmentSummary(BaseModel):
    month: str
    items: List[DepartmentSummaryItem]


class LeaderboardItem(BaseModel):
    rank: int
    emp_code: str
    name: str
    department: str
    total_late_minutes: int
    late_count: int


class Leaderboard(BaseModel):
    month: str
    items: List[LeaderboardItem]


class TrendItem(BaseModel):
    date: str
    is_working_day: bool
    headcount: int
    present_count: float
    late_count: int
    attendance_rate: Optional[float]
    moving_avg_7d: Optional[float]


class Trend(BaseModel):
    department: str
    items: List[TrendItem]


class ExplainResponse(BaseModel):
    endpoint: str
    collection: str
    explain: dict


# --------------------------------------------------------------------------- #
# Startup - Create Indexes
# --------------------------------------------------------------------------- #
@app.on_event("startup")
def create_indexes():
    """Create required indexes at startup (idempotent)."""
    try:
        # Employees: unique index on emp_code
        db.employees.create_index([("emp_code", ASCENDING)], unique=True)
        
        # Attendance logs: compound index on emp_code + date for lookups
        db.attendance_logs.create_index([("emp_code", ASCENDING), ("date", ASCENDING)], unique=True)
        
        # Attendance logs: index on date for date range queries
        db.attendance_logs.create_index([("date", DESCENDING)])
        
        # Attendance logs: index on status for filtering
        db.attendance_logs.create_index([("status", ASCENDING)])
        
        # Attendance logs: compound index for analytics (date + status)
        db.attendance_logs.create_index([("date", ASCENDING), ("status", ASCENDING)])
    except Exception as e:
        print(f"Warning: Index creation failed: {e}")
        print("Continuing without indexes - performance may be degraded")


# --------------------------------------------------------------------------- #
# System Endpoints
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    """Readiness probe - returns 503 if MongoDB doesn't respond."""
    try:
        client.admin.command('ping')
        return {"status": "ok"}
    except Exception:
        raise HTTPException(status_code=503, detail="MongoDB not responding")


# --------------------------------------------------------------------------- #
# Employee Endpoints
# --------------------------------------------------------------------------- #
@app.post("/employees", status_code=201, response_model=Employee)
def create_employee(body: EmployeeCreate):
    """Create an employee."""
    doc = body.model_dump()
    doc["created_at"] = datetime.now(timezone.utc)
    
    try:
        db.employees.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="emp_code already exists")
    
    doc.pop("_id", None)
    doc["created_at"] = datetime_to_epoch(doc["created_at"])
    return doc


@app.get("/employees", response_model=EmployeePage)
def list_employees(
    department: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100)
):
    """List employees, sorted by emp_code ascending."""
    q = {}
    if department:
        q["department"] = department
    
    skip = (page - 1) * page_size
    total = db.employees.count_documents(q)
    
    items = list(
        db.employees
        .find(q, {"_id": 0})
        .sort("emp_code", ASCENDING)
        .skip(skip)
        .limit(page_size)
    )
    
    # Convert created_at to epoch milliseconds
    for item in items:
        item["created_at"] = datetime_to_epoch(item["created_at"])
    
    return {"items": items, "total": total, "page": page, "page_size": page_size}


# --------------------------------------------------------------------------- #
# Attendance Endpoints
# --------------------------------------------------------------------------- #
@app.post("/attendance/punch-in", status_code=201, response_model=AttendanceRecord)
def punch_in(body: PunchInRequest):
    """Record a punch-in."""
    # Validate status
    if body.status not in PRESENCE_STATUS_VALUES:
        raise HTTPException(status_code=422, detail=f"status must be one of {PRESENCE_STATUS_VALUES}")
    
    # Get employee
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    
    # Get punch time
    if body.punched_at:
        ts = epoch_to_datetime(body.punched_at)
    else:
        ts = datetime.now(timezone.utc)
    
    # Truncate to seconds (R1)
    ts = truncate_to_seconds(ts)
    
    # Calculate attendance date (R1)
    attendance_date = calculate_attendance_date(ts, emp["shift_start"], emp["shift_end"])
    
    # Check if already punched in
    existing = db.attendance_logs.find_one({"emp_code": body.emp_code, "date": attendance_date})
    if existing:
        raise HTTPException(status_code=409, detail="already punched in for this date")
    
    # Create record
    doc = {
        "emp_code": body.emp_code,
        "date": attendance_date,
        "status": body.status,
        "punch_in": ts,
        "punch_out": None,
        "work_hours": None,
        "late_minutes": compute_late_minutes(ts, emp["shift_start"]),
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
    }
    
    db.attendance_logs.insert_one(doc)
    
    # Convert to response format
    doc["punch_in"] = datetime_to_epoch(doc["punch_in"])
    doc.pop("_id", None)
    return doc


@app.post("/attendance/punch-out", response_model=AttendanceRecord)
def punch_out(body: PunchOutRequest):
    """Record a punch-out."""
    # Get employee
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    
    # Get punch time
    if body.punched_at:
        ts = epoch_to_datetime(body.punched_at)
    else:
        ts = datetime.now(timezone.utc)
    
    # Truncate to seconds (R1)
    ts = truncate_to_seconds(ts)
    
    # Find most recent punch-in at or before punched_at
    record = db.attendance_logs.find_one({
        "emp_code": body.emp_code,
        "punch_in": {"$lte": ts},
        "punch_out": None
    }, sort=[("punch_in", DESCENDING)])
    
    if not record:
        raise HTTPException(status_code=404, detail="No punch-in found")
    
    # Validate punch_out > punch_in
    punch_in_aware = record["punch_in"].replace(tzinfo=timezone.utc) if record["punch_in"].tzinfo is None else record["punch_in"]
    if ts <= punch_in_aware:
        raise HTTPException(status_code=422, detail="punch_out must be after punch_in")
    
    # Validate punch_out within 24 hours of punch_in
    if (ts - punch_in_aware).total_seconds() > 24 * 3600:
        raise HTTPException(status_code=422, detail="punch_out must be within 24 hours of punch_in")
    
    # Check if already punched out (concurrent check)
    if record["punch_out"] is not None:
        raise HTTPException(status_code=409, detail="already punched out")
    
    # Compute derived fields
    punch_in_aware = record["punch_in"].replace(tzinfo=timezone.utc) if record["punch_in"].tzinfo is None else record["punch_in"]
    work_hours = compute_work_hours(punch_in_aware, ts)
    overtime_minutes = compute_overtime_minutes(ts, emp["shift_end"], record["date"])
    half_day = compute_half_day(work_hours)
    
    # Update record - store punch_out as UTC datetime
    update = {
        "$set": {
            "punch_out": ts,
            "work_hours": work_hours,
            "overtime_minutes": overtime_minutes,
            "half_day": half_day
        }
    }
    
    result = db.attendance_logs.update_one(
        {"_id": record["_id"], "punch_out": None},
        update
    )
    
    if result.modified_count == 0:
        raise HTTPException(status_code=409, detail="already punched out")
    
    # Fetch updated record
    updated = db.attendance_logs.find_one({"_id": record["_id"]})
    updated.pop("_id", None)
    updated["punch_in"] = datetime_to_epoch(updated["punch_in"])
    updated["punch_out"] = datetime_to_epoch(updated["punch_out"])
    
    return updated


@app.get("/attendance", response_model=AttendancePage)
def list_attendance(
    emp_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100)
):
    """List attendance records, sorted by date desc, emp_code asc."""
    # Validate date range
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="date_from must not be greater than date_to")
    
    q = {}
    if emp_code:
        q["emp_code"] = emp_code
    if date_from or date_to:
        q["date"] = {}
        if date_from:
            q["date"]["$gte"] = date_from
        if date_to:
            q["date"]["$lte"] = date_to
    if status:
        q["status"] = status
    
    skip = (page - 1) * page_size
    total = db.attendance_logs.count_documents(q)
    
    items = list(
        db.attendance_logs
        .find(q, {"_id": 0})
        .sort([("date", DESCENDING), ("emp_code", ASCENDING)])
        .skip(skip)
        .limit(page_size)
    )
    
    # Convert datetime to epoch milliseconds and ensure required fields
    for item in items:
        if item["punch_in"]:
            item["punch_in"] = datetime_to_epoch(item["punch_in"])
        if item["punch_out"]:
            item["punch_out"] = datetime_to_epoch(item["punch_out"])
        # Ensure half_day and history are present (legacy records)
        if "half_day" not in item:
            item["half_day"] = False
        if "history" not in item:
            item["history"] = []
        # Convert history.at to epoch milliseconds
        for entry in item["history"]:
            if isinstance(entry["at"], datetime):
                entry["at"] = datetime_to_epoch(entry["at"])
            # Convert punch_in/punch_out in changes to epoch milliseconds
            if "changes" in entry:
                for field in ["punch_in", "punch_out"]:
                    if field in entry["changes"]:
                        from_val = entry["changes"][field]["from"]
                        to_val = entry["changes"][field]["to"]
                        if from_val is not None:
                            if isinstance(from_val, datetime):
                                entry["changes"][field]["from"] = datetime_to_epoch(from_val)
                            elif isinstance(from_val, str):
                                # Parse ISO string to datetime
                                try:
                                    entry["changes"][field]["from"] = datetime_to_epoch(datetime.fromisoformat(from_val))
                                except:
                                    pass  # Keep as-is if parsing fails
                        if to_val is not None:
                            if isinstance(to_val, datetime):
                                entry["changes"][field]["to"] = datetime_to_epoch(to_val)
                            elif isinstance(to_val, str):
                                # Parse ISO string to datetime
                                try:
                                    entry["changes"][field]["to"] = datetime_to_epoch(datetime.fromisoformat(to_val))
                                except:
                                    pass  # Keep as-is if parsing fails
    
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@app.patch("/attendance/{emp_code}/{date}", response_model=AttendanceRecord)
def regularize_attendance(emp_code: str, date: str, body: RegularizeRequest):
    """Regularize (manually correct) one day's record."""
    # Get employee
    emp = db.employees.find_one({"emp_code": emp_code})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    
    # Get existing record
    record = db.attendance_logs.find_one({"emp_code": emp_code, "date": date})
    if not record:
        raise HTTPException(status_code=404, detail="Attendance record not found")
    
    # Track changes
    changes = {}
    old_values = {}
    
    # Handle status change
    if body.status is not None:
        if body.status not in STATUS_VALUES:
            raise HTTPException(status_code=422, detail=f"Invalid status: {body.status}")
        
        if body.status != record["status"]:
            # If setting to ABSENT or LEAVE, must clear punch times
            if body.status in ["ABSENT", "LEAVE"]:
                if body.punch_in is not None or body.punch_out is not None:
                    raise HTTPException(status_code=422, detail="Cannot set punch times with ABSENT/LEAVE status")
                changes["status"] = {"from": record["status"], "to": body.status}
                old_values["status"] = record["status"]
                record["status"] = body.status
                record["punch_in"] = None
                record["punch_out"] = None
                changes["punch_in"] = {"from": datetime_to_epoch(record["punch_in"]) if record.get("punch_in") else None, "to": None}
                changes["punch_out"] = {"from": datetime_to_epoch(record["punch_out"]) if record.get("punch_out") else None, "to": None}
            else:
                # Presence status requires punch_in
                if body.punch_in is None and record.get("punch_in") is None:
                    raise HTTPException(status_code=422, detail="Presence status requires punch_in")
                changes["status"] = {"from": record["status"], "to": body.status}
                old_values["status"] = record["status"]
                record["status"] = body.status
    
    # Handle punch_in change
    if body.punch_in is not None:
        new_punch_in = truncate_to_seconds(epoch_to_datetime(body.punch_in))
        # Validate punch_in is on the attendance date (R1)
        attendance_date = calculate_attendance_date(new_punch_in, emp["shift_start"], emp["shift_end"])
        if attendance_date != date:
            raise HTTPException(status_code=422, detail="punch_in must be on the attendance date")
        
        old_punch_in = record.get("punch_in")
        if old_punch_in is None:
            changes["punch_in"] = {"from": None, "to": body.punch_in}
        elif datetime_to_epoch(old_punch_in) != body.punch_in:
            changes["punch_in"] = {"from": datetime_to_epoch(old_punch_in), "to": body.punch_in}
        
        record["punch_in"] = new_punch_in
    
    # Handle punch_out change
    if body.punch_out is not None:
        new_punch_out = truncate_to_seconds(epoch_to_datetime(body.punch_out))
        
        # Validate punch_out > punch_in
        if record.get("punch_in") and new_punch_out <= record["punch_in"]:
            raise HTTPException(status_code=422, detail="punch_out must be after punch_in")
        
        # Validate within 24 hours
        if record.get("punch_in") and (new_punch_out - record["punch_in"]).total_seconds() > 24 * 3600:
            raise HTTPException(status_code=422, detail="punch_out must be within 24 hours of punch_in")
        
        old_punch_out = record.get("punch_out")
        if old_punch_out is None:
            changes["punch_out"] = {"from": None, "to": body.punch_out}
        elif datetime_to_epoch(old_punch_out) != body.punch_out:
            changes["punch_out"] = {"from": datetime_to_epoch(old_punch_out), "to": body.punch_out}
        
        record["punch_out"] = new_punch_out
    
    # If no changes, return 422
    if not changes:
        raise HTTPException(status_code=422, detail="No changes to apply")
    
    # Recompute derived fields
    if record["punch_in"]:
        record["late_minutes"] = compute_late_minutes(record["punch_in"], emp["shift_start"])
        
        if record["punch_out"]:
            work_hours = compute_work_hours(record["punch_in"], record["punch_out"])
            overtime_minutes = compute_overtime_minutes(record["punch_out"], emp["shift_end"], record["date"])
            half_day = compute_half_day(work_hours)
            
            old_work_hours = record.get("work_hours")
            old_overtime = record.get("overtime_minutes", 0)
            old_half_day = record.get("half_day", False)
            
            record["work_hours"] = work_hours
            record["overtime_minutes"] = overtime_minutes
            record["half_day"] = half_day
            
            if old_work_hours != work_hours:
                changes["work_hours"] = {"from": old_work_hours, "to": work_hours}
            if old_overtime != overtime_minutes:
                changes["overtime_minutes"] = {"from": old_overtime, "to": overtime_minutes}
            if old_half_day != half_day:
                changes["half_day"] = {"from": old_half_day, "to": half_day}
        else:
            # No punch_out, reset derived fields
            old_work_hours = record.get("work_hours")
            old_overtime = record.get("overtime_minutes", 0)
            old_half_day = record.get("half_day", False)
            
            record["work_hours"] = None
            record["overtime_minutes"] = 0
            record["half_day"] = False
            
            if old_work_hours is not None:
                changes["work_hours"] = {"from": old_work_hours, "to": None}
            if old_overtime != 0:
                changes["overtime_minutes"] = {"from": old_overtime, "to": 0}
            if old_half_day:
                changes["half_day"] = {"from": old_half_day, "to": False}
    else:
        # No punch_in, reset all derived fields
        old_late = record.get("late_minutes", 0)
        old_work_hours = record.get("work_hours")
        old_overtime = record.get("overtime_minutes", 0)
        old_half_day = record.get("half_day", False)
        
        record["late_minutes"] = 0
        record["work_hours"] = None
        record["overtime_minutes"] = 0
        record["half_day"] = False
        
        if old_late != 0:
            changes["late_minutes"] = {"from": old_late, "to": 0}
        if old_work_hours is not None:
            changes["work_hours"] = {"from": old_work_hours, "to": None}
        if old_overtime != 0:
            changes["overtime_minutes"] = {"from": old_overtime, "to": 0}
        if old_half_day:
            changes["half_day"] = {"from": old_half_day, "to": False}
    
    # Append history entry
    history_entry = {
        "at": datetime.now(timezone.utc),
        "by": body.regularized_by,
        "reason": body.reason,
        "changes": changes
    }
    
    if "history" not in record:
        record["history"] = []
    record["history"].append(history_entry)
    
    # Update in database
    db.attendance_logs.update_one(
        {"_id": record["_id"]},
        {"$set": {
            "status": record["status"],
            "punch_in": record["punch_in"],
            "punch_out": record["punch_out"],
            "work_hours": record["work_hours"],
            "late_minutes": record["late_minutes"],
            "overtime_minutes": record["overtime_minutes"],
            "half_day": record["half_day"],
            "history": record["history"]
        }}
    )
    
    # Convert to response format
    response = record.copy()
    response.pop("_id", None)
    if response["punch_in"]:
        response["punch_in"] = datetime_to_epoch(response["punch_in"])
    if response["punch_out"]:
        response["punch_out"] = datetime_to_epoch(response["punch_out"])
    
    # Convert history.at to epoch milliseconds
    for entry in response["history"]:
        entry["at"] = datetime_to_epoch(entry["at"])
    
    return response


# --------------------------------------------------------------------------- #
# Analytics Endpoints
# --------------------------------------------------------------------------- #
@app.get("/analytics/employees/{emp_code}/monthly", response_model=EmployeeMonthly)
def employee_monthly(emp_code: str, month: str = Query(..., pattern=r'^\d{4}-(0[1-9]|1[0-2])$')):
    """Monthly attendance summary for one employee."""
    # Check employee exists
    emp = db.employees.find_one({"emp_code": emp_code})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    
    # Calculate working days (R7)
    year, month_num = map(int, month.split("-"))
    # First day of month
    first_day = datetime(year, month_num, 1)
    # Last day of month
    if month_num == 12:
        last_day = datetime(year + 1, 1, 1) - timedelta(days=1)
    else:
        last_day = datetime(year, month_num + 1, 1) - timedelta(days=1)
    
    # Working days from joined_on
    joined_date = datetime.fromisoformat(emp["joined_on"])
    working_start = max(joined_date, first_day)
    
    working_days = 0
    current = working_start
    while current <= last_day:
        if is_working_day(current.date().isoformat()):
            working_days += 1
        current += timedelta(days=1)
    
    # Aggregate attendance logs
    pipeline = [
        {"$match": {
            "emp_code": emp_code,
            "date": {"$gte": month, "$lt": f"{year}-{month_num+1:02d}" if month_num < 12 else f"{year+1}-01"}
        }},
        {"$group": {
            "_id": "$status",
            "count": {"$sum": 1},
            "total_late_minutes": {"$sum": "$late_minutes"},
            "total_overtime_minutes": {"$sum": "$overtime_minutes"},
            "late_count": {
                "$sum": {"$cond": [{"$gt": ["$late_minutes", 0]}, 1, 0]}
            },
            "work_hours_sum": {"$sum": {"$ifNull": ["$work_hours", 0]}},
            "half_day_count": {
                "$sum": {"$cond": [{"$eq": ["$half_day", True]}, 1, 0]}
            }
        }}
    ]
    
    results = list(db.attendance_logs.aggregate(pipeline))
    
    # Calculate present_days (R5-R7: half day = 0.5, Mon-Fri only)
    present_days = 0.0
    leave_days = 0
    late_count = 0
    total_late_minutes = 0
    total_overtime_minutes = 0
    
    for r in results:
        status = r["_id"]
        if status in PRESENCE_STATUS_VALUES:
            # Count only Mon-Fri records
            for record in db.attendance_logs.find({
                "emp_code": emp_code,
                "date": {"$gte": month, "$lt": f"{year}-{month_num+1:02d}" if month_num < 12 else f"{year+1}-01"},
                "status": status
            }):
                if is_working_day(record["date"]):
                    if record.get("half_day", False):
                        present_days += 0.5
                    else:
                        present_days += 1
        elif status == "LEAVE":
            leave_days = r["count"]
        
        late_count += r.get("late_count", 0)
        total_late_minutes += r.get("total_late_minutes", 0)
        total_overtime_minutes += r.get("total_overtime_minutes", 0)
    
    # Calculate attendance percentage
    attendance_pct = None
    if working_days > 0:
        attendance_pct = round_half_up((present_days / working_days) * 100, 2)
    
    return {
        "emp_code": emp_code,
        "month": month,
        "working_days": working_days,
        "present_days": round_half_up(present_days, 2),
        "leave_days": leave_days,
        "late_count": late_count,
        "total_late_minutes": total_late_minutes,
        "total_overtime_minutes": total_overtime_minutes,
        "attendance_pct": attendance_pct
    }


@app.get("/analytics/departments/summary", response_model=DepartmentSummary)
def department_summary(
    month: str = Query(..., pattern=r'^\d{4}-(0[1-9]|1[0-2])$'),
    department: Optional[str] = None
):
    """Department summary for a month."""
    year, month_num = map(int, month.split("-"))
    month_end = f"{year}-{month_num+1:02d}" if month_num < 12 else f"{year+1}-01"
    
    # Build match stage
    match_stage = {"date": {"$gte": month, "$lt": month_end}}
    if department:
        match_stage["department"] = department
    
    # Get employees for headcount (R9)
    last_day = datetime(year, month_num, 28)  # Simplified, should get actual last day
    if month_num == 12:
        last_day = datetime(year + 1, 1, 1) - timedelta(days=1)
    else:
        last_day = datetime(year, month_num + 1, 1) - timedelta(days=1)
    
    emp_match = {"joined_on": {"$lte": last_day.date().isoformat()}}
    if department:
        emp_match["department"] = department
    
    departments = db.employees.distinct("department", emp_match)
    
    items = []
    for dept in departments:
        # Headcount
        dept_emp_match = emp_match.copy()
        dept_emp_match["department"] = dept
        headcount = db.employees.count_documents(dept_emp_match)
        
        if headcount == 0:
            continue
        
        # Get employee codes in this department
        emp_codes = [e["emp_code"] for e in db.employees.find(dept_emp_match, {"emp_code": 1})]
        
        # Aggregate attendance for this department
        pipeline = [
            {"$match": {
                "emp_code": {"$in": emp_codes},
                "date": {"$gte": month, "$lt": month_end}
            }},
            {"$group": {
                "_id": "$status",
                "count": {"$sum": 1},
                "total_late_minutes": {"$sum": "$late_minutes"},
                "late_count": {
                    "$sum": {"$cond": [{"$gt": ["$late_minutes", 0]}, 1, 0]}
                },
                "work_hours_sum": {"$sum": {"$ifNull": ["$work_hours", 0]}},
                "work_hours_count": {
                    "$sum": {"$cond": [{"$ne": ["$work_hours", None]}, 1, 0]}
                },
                "half_day_count": {
                    "$sum": {"$cond": [{"$eq": ["$half_day", True]}, 1, 0]}
                }
            }}
        ]
        
        results = list(db.attendance_logs.aggregate(pipeline))
        
        present_days = 0.0
        late_count = 0
        total_late_minutes = 0
        leave_count = 0
        on_duty_count = 0
        work_hours_sum = 0.0
        work_hours_count = 0
        
        for r in results:
            status = r["_id"]
            if status in PRESENCE_STATUS_VALUES:
                # Count only Mon-Fri
                for record in db.attendance_logs.find({
                    "emp_code": {"$in": emp_codes},
                    "date": {"$gte": month, "$lt": month_end},
                    "status": status
                }):
                    if is_working_day(record["date"]):
                        if record.get("half_day", False):
                            present_days += 0.5
                        else:
                            present_days += 1
            elif status == "LEAVE":
                leave_count = r["count"]
            elif status == "ON_DUTY":
                on_duty_count = r["count"]
            
            late_count += r.get("late_count", 0)
            total_late_minutes += r.get("total_late_minutes", 0)
            work_hours_sum += r.get("work_hours_sum", 0)
            work_hours_count += r.get("work_hours_count", 0)
        
        avg_work_hours = None
        if work_hours_count > 0:
            avg_work_hours = round_half_up(work_hours_sum / work_hours_count, 2)
        
        items.append({
            "department": dept,
            "headcount": headcount,
            "present_days": round_half_up(present_days, 2),
            "avg_work_hours": avg_work_hours,
            "late_count": late_count,
            "total_late_minutes": total_late_minutes,
            "leave_count": leave_count,
            "on_duty_count": on_duty_count
        })
    
    # Sort by department ascending
    items.sort(key=lambda x: x["department"])
    
    return {"month": month, "items": items}


@app.get("/analytics/leaderboard/late", response_model=Leaderboard)
def late_leaderboard(
    month: str = Query(..., pattern=r'^\d{4}-(0[1-9]|1[0-2])$'),
    limit: int = Query(default=10, ge=1, le=50),
    department: Optional[str] = None
):
    """Late-comers leaderboard for a month."""
    year, month_num = map(int, month.split("-"))
    month_end = f"{year}-{month_num+1:02d}" if month_num < 12 else f"{year+1}-01"
    
    # Build match stage
    match_stage = {
        "date": {"$gte": month, "$lt": month_end},
        "late_minutes": {"$gt": 0}
    }
    
    # Join with employees
    pipeline = [
        {"$match": match_stage},
        {"$lookup": {
            "from": "employees",
            "localField": "emp_code",
            "foreignField": "emp_code",
            "as": "emp"
        }},
        {"$unwind": "$emp"},
        {"$project": {
            "emp_code": 1,
            "name": "$emp.name",
            "department": "$emp.department",
            "late_minutes": 1
        }}
    ]
    
    if department:
        pipeline.append({"$match": {"department": department}})
    
    pipeline.extend([
        {"$group": {
            "_id": "$emp_code",
            "name": {"$first": "$name"},
            "department": {"$first": "$department"},
            "total_late_minutes": {"$sum": "$late_minutes"},
            "late_count": {"$sum": 1}
        }},
        {"$sort": {"total_late_minutes": DESCENDING, "_id": ASCENDING}}
    ])
    
    results = list(db.attendance_logs.aggregate(pipeline))
    
    # Apply standard competition ranking
    ranked = []
    current_rank = 1
    i = 0
    while i < len(results):
        current_late = results[i]["total_late_minutes"]
        # Find all with same late_minutes
        j = i
        while j < len(results) and results[j]["total_late_minutes"] == current_late:
            j += 1
        
        # All from i to j-1 get the same rank
        for k in range(i, j):
            ranked.append({
                "rank": current_rank,
                "emp_code": results[k]["_id"],
                "name": results[k]["name"],
                "department": results[k]["department"],
                "total_late_minutes": results[k]["total_late_minutes"],
                "late_count": results[k]["late_count"]
            })
        
        # Next rank skips the tied count
        current_rank += (j - i) + 1
        i = j
    
    # Filter by rank <= limit
    items = [r for r in ranked if r["rank"] <= limit]
    
    return {"month": month, "items": items}


@app.get("/analytics/departments/{department}/trend", response_model=Trend)
def department_trend(
    department: str,
    from_: str = Query(..., alias='from', format='date'),
    to: str = Query(..., format='date')
):
    """Daily attendance trend for a department."""
    # Validate department exists
    if db.employees.count_documents({"department": department}) == 0:
        raise HTTPException(status_code=404, detail="Department not found")
    
    # Validate date range
    if to < from_:
        raise HTTPException(status_code=422, detail="to must not be less than from")
    
    # Validate range doesn't exceed 92 days
    from_dt = datetime.fromisoformat(from_)
    to_dt = datetime.fromisoformat(to)
    if (to_dt - from_dt).days > 92:
        raise HTTPException(status_code=422, detail="Date range cannot exceed 92 days")
    
    # Get employee codes in department
    emp_codes = [e["emp_code"] for e in db.employees.find({"department": department}, {"emp_code": 1})]
    
    # Generate all dates in range using densify
    pipeline = [
        {"$match": {
            "emp_code": {"$in": emp_codes},
            "date": {"$gte": from_, "$lte": to}
        }},
        {"$group": {
            "_id": "$date",
            "present_count": {
                "$sum": {
                    "$cond": [
                        {"$in": ["$status", PRESENCE_STATUS_VALUES]},
                        {"$cond": [{"$eq": ["$half_day", True]}, 0.5, 1]},
                        0
                    ]
                }
            },
            "late_count": {
                "$sum": {"$cond": [{"$gt": ["$late_minutes", 0]}, 1, 0]}
            }
        }},
        {"$sort": {"_id": ASCENDING}}
    ]
    
    attendance_by_date = {r["_id"]: r for r in db.attendance_logs.aggregate(pipeline)}
    
    # Generate all dates
    items = []
    current = from_dt
    non_null_rates = []
    
    while current <= to_dt:
        date_str = current.date().isoformat()
        is_working = is_working_day(date_str)
        
        # Headcount: employees with joined_on <= this day
        headcount = db.employees.count_documents({
            "emp_code": {"$in": emp_codes},
            "joined_on": {"$lte": date_str}
        })
        
        # Present count
        present_count = 0.0
        late_count = 0
        if date_str in attendance_by_date:
            present_count = attendance_by_date[date_str]["present_count"]
            late_count = attendance_by_date[date_str]["late_count"]
        
        # Attendance rate
        attendance_rate = None
        if is_working and headcount > 0:
            attendance_rate = round_half_up((present_count / headcount) * 100, 4)
            non_null_rates.append(attendance_rate)
        elif is_working and headcount > 0:
            attendance_rate = 0.0
            non_null_rates.append(attendance_rate)
        
        # Moving average (7-day window)
        moving_avg = None
        if non_null_rates:
            window = non_null_rates[-7:] if len(non_null_rates) >= 7 else non_null_rates
            moving_avg = round_half_up(sum(window) / len(window), 4)
        
        items.append({
            "date": date_str,
            "is_working_day": is_working,
            "headcount": headcount,
            "present_count": round_half_up(present_count, 2),
            "late_count": late_count,
            "attendance_rate": attendance_rate,
            "moving_avg_7d": moving_avg
        })
        
        current += timedelta(days=1)
    
    return {"department": department, "items": items}


# --------------------------------------------------------------------------- #
# Admin Endpoints
# --------------------------------------------------------------------------- #
@app.get("/admin/explain/{endpoint}", response_model=ExplainResponse)
def explain_endpoint(
    endpoint: str,
    emp_code: Optional[str] = None,
    month: Optional[str] = None,
    department: Optional[str] = None,
    limit: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    from_: Optional[str] = Query(None, alias='from'),
    to: Optional[str] = None,
    page: Optional[int] = None,
    page_size: Optional[int] = None
):
    """MongoDB explain for an endpoint's main query."""
    valid_endpoints = ["attendance_list", "employee_monthly", "department_summary", "late_leaderboard", "department_trend"]
    if endpoint not in valid_endpoints:
        raise HTTPException(status_code=422, detail=f"Invalid endpoint: {endpoint}")
    
    collection = "attendance_logs"
    pipeline = None
    query = None
    
    if endpoint == "attendance_list":
        collection = "attendance_logs"
        q = {}
        if emp_code:
            q["emp_code"] = emp_code
        if date_from or date_to:
            q["date"] = {}
            if date_from:
                q["date"]["$gte"] = date_from
            if date_to:
                q["date"]["$lte"] = date_to
        if status:
            q["status"] = status
        query = q
        
    elif endpoint == "employee_monthly":
        if not emp_code or not month:
            raise HTTPException(status_code=422, detail="emp_code and month required")
        collection = "attendance_logs"
        year, month_num = map(int, month.split("-"))
        pipeline = [
            {"$match": {
                "emp_code": emp_code,
                "date": {"$gte": month, "$lt": f"{year}-{month_num+1:02d}" if month_num < 12 else f"{year+1}-01"}
            }},
            {"$group": {
                "_id": "$status",
                "count": {"$sum": 1}
            }}
        ]
        
    elif endpoint == "department_summary":
        if not month:
            raise HTTPException(status_code=422, detail="month required")
        collection = "attendance_logs"
        year, month_num = map(int, month.split("-"))
        match_stage = {"date": {"$gte": month, "$lt": f"{year}-{month_num+1:02d}" if month_num < 12 else f"{year+1}-01"}}
        if department:
            # Would need to join with employees, simplified here
            pass
        pipeline = [
            {"$match": match_stage},
            {"$group": {
                "_id": "$status",
                "count": {"$sum": 1}
            }}
        ]
        
    elif endpoint == "late_leaderboard":
        if not month:
            raise HTTPException(status_code=422, detail="month required")
        collection = "attendance_logs"
        year, month_num = map(int, month.split("-"))
        match_stage = {
            "date": {"$gte": month, "$lt": f"{year}-{month_num+1:02d}" if month_num < 12 else f"{year+1}-01"},
            "late_minutes": {"$gt": 0}
        }
        pipeline = [
            {"$match": match_stage},
            {"$lookup": {
                "from": "employees",
                "localField": "emp_code",
                "foreignField": "emp_code",
                "as": "emp"
            }},
            {"$unwind": "$emp"},
            {"$group": {
                "_id": "$emp_code",
                "total_late_minutes": {"$sum": "$late_minutes"}
            }},
            {"$sort": {"total_late_minutes": DESCENDING}}
        ]
        
    elif endpoint == "department_trend":
        if not from_ or not to:
            raise HTTPException(status_code=422, detail="from and to required")
        collection = "attendance_logs"
        pipeline = [
            {"$match": {
                "date": {"$gte": from_, "$lte": to}
            }},
            {"$group": {
                "_id": "$date",
                "count": {"$sum": 1}
            }}
        ]
    
    # Run explain
    if pipeline:
        explain_result = db.attendance_logs.aggregate(pipeline, explain=True)
    else:
        explain_result = db.attendance_logs.find(query).explain()
    
    return {
        "endpoint": endpoint,
        "collection": collection,
        "explain": explain_result
    }
