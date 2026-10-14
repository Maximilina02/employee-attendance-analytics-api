

"""

Employee Attendance & Analytics API

FastAPI + MongoDB

Run:

          python -m uvicorn app.main:app --reload --port 8000

Environment variables:

          MONGO_URI

          MONGO_DB

"""

import os

import math

from datetime import datetime, date, time, timedelta, timezone

from decimal import Decimal, ROUND_HALF_UP

from typing import Optional, Any

from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, Query

from pydantic import BaseModel, ConfigDict, Field, field_validator

from pymongo import MongoClient, ASCENDING, DESCENDING

from pymongo.errors import DuplicateKeyError, PyMongoError

from bson import ObjectId, Timestamp

# ---------------------------------------------------------------------------

# Configuration and database

# ---------------------------------------------------------------------------

load_dotenv()

IST = timezone(timedelta(hours=5, minutes=30))

UTC = timezone.utc

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")

MONGO_DB = os.getenv("MONGO_DB", "attendance_db")

client = MongoClient(

          MONGO_URI,

          tz_aware=True,

          serverSelectionTimeoutMS=5000,

)

db = client[MONGO_DB]

app = FastAPI(

          title="Employee Attendance & Analytics API",

          version="2.0.0",

)

@app.on_event("startup")

def create_indexes():

          """Create indexes used by the API."""

          db.employees.create_index(

                    [("emp_code", ASCENDING)],

                    unique=True,

          )

          db.attendance_logs.create_index(

                    [("emp_code", ASCENDING), ("date", ASCENDING)],

                    unique=True,

          )

          db.attendance_logs.create_index(

                    [("date", DESCENDING)],

          )

          db.employees.create_index(

                    [("department", ASCENDING)],

          )

# ---------------------------------------------------------------------------

# General helpers

# ---------------------------------------------------------------------------

def now_utc() -> datetime:

          return datetime.now(UTC)

def to_utc(value: datetime) -> datetime:

          """Normalize a datetime to an aware UTC datetime."""

          if value.tzinfo is None:

                    # Naive timestamps from MongoDB are interpreted as UTC.

                    value = value.replace(tzinfo=UTC)

          return value.astimezone(UTC)

def to_ist(value: datetime) -> datetime:

          return to_utc(value).astimezone(IST)

def parse_epoch_ms(value: int) -> datetime:
    """Accept integer epoch milliseconds only, not seconds, floats, or strings."""
    if isinstance(value, bool) or not isinstance(value, int) or abs(value) < 100_000_000_000:
        raise HTTPException(422, "Timestamp must be an integer epoch-millisecond value")
    try:
        parsed = datetime.fromtimestamp(value / 1000, tz=UTC)
    except (ValueError, OverflowError, OSError):
        raise HTTPException(422, "Invalid epoch-millisecond timestamp")
    # API contract requires whole-second precision.
    return parsed.replace(microsecond=0)

def to_epoch_ms(value: Optional[datetime]) -> Optional[int]:

          if value is None:

                    return None

          return int(to_utc(value).timestamp() * 1000)

def attendance_date(value: datetime, shift_start: Optional[str] = None, shift_end: Optional[str] = None) -> str:
    """Return the IST attendance date, adjusting overnight shifts per R1."""
    local = to_ist(value)
    day = local.date()
    if shift_start is not None and shift_end is not None:
        start_h, start_m = parse_clock(shift_start)
        end_h, end_m = parse_clock(shift_end)
        start_minutes = start_h * 60 + start_m
        end_minutes = end_h * 60 + end_m
        local_minutes = local.hour * 60 + local.minute
        if end_minutes <= start_minutes and local_minutes < end_minutes:
            day -= timedelta(days=1)
    return day.isoformat()

def parse_date(value: str) -> date:

          try:

                    return date.fromisoformat(value)

          except (ValueError, TypeError):

                    raise HTTPException(422, f"Invalid date: {value}. Use YYYY-MM-DD.")

def parse_clock(value: str) -> tuple[int, int]:

          try:

                    parsed = time.fromisoformat(value)

                    if parsed.second != 0 or parsed.microsecond != 0:

                              raise ValueError

                    return parsed.hour, parsed.minute

          except (ValueError, TypeError):

                    raise HTTPException(

                              422,

                              f"Invalid shift time: {value}. Use HH:MM.",

                    )



def serialize_value(value: Any) -> Any:
    """Convert MongoDB and BSON values to JSON-safe API values."""

    if isinstance(value, ObjectId):
        return str(value)

    if isinstance(value, Timestamp):
        return {
            "time": value.time,
            "increment": value.inc,
        }

    if isinstance(value, datetime):
        return to_epoch_ms(value)

    if isinstance(value, bytes):
        return {
            "type": "binary",
            "hex": value.hex(),
        }

    if isinstance(value, dict):
        return {
            ("id" if key == "_id" else key): serialize_value(item)
            for key, item in value.items()
            if key != "_id"
        }

    if isinstance(value, (list, tuple)):
        return [serialize_value(item) for item in value]

    return value


def public_attendance(doc: dict) -> dict:

          result = {key: value for key, value in doc.items() if key != "_id" and key != "id"}

          # Expose timestamps in epoch milliseconds.

          for key in ("punch_in", "punch_out"):

                    if result.get(key) is not None:

                              result[key] = to_epoch_ms(result[key])

          result["history"] = serialize_value(result.get("history", []))

          return result

def get_employee(emp_code: str) -> dict:

          emp = db.employees.find_one({"emp_code": emp_code})

          if not emp:

                    raise HTTPException(404, f"Employee {emp_code} not found")

          return emp

def get_attendance(emp_code: str, date_str: str) -> dict:

          doc = db.attendance_logs.find_one({

                    "emp_code": emp_code,

                    "date": date_str,

          })

          if not doc:

                    raise HTTPException(

                              404,

                              f"Attendance not found for {emp_code} on {date_str}",

                    )

          return doc

def paginated_result(

          items: list,

          total: int,

          page: int,

          page_size: int,

) -> dict:

          return {

                    "items": items,

                    "total": total,

                    "page": page,

                    "page_size": page_size,

          }

def validate_pagination(page: int, page_size: int):

          if page < 1:

                    raise HTTPException(422, "page must be positive")

          if page_size < 1 or page_size > 100:

                    raise HTTPException(422, "page_size must be between 1 and 100")

# ---------------------------------------------------------------------------

# Attendance calculation helpers

# ---------------------------------------------------------------------------

def shift_end_datetime(

          date_str: str,

          shift_start: str,

          shift_end: str,

) -> datetime:

          """

          Return shift end in IST.

          If shift_end is earlier than or equal to shift_start, the shift

          is treated as an overnight shift.

          """

          day = parse_date(date_str)

          start_h, start_m = parse_clock(shift_start)

          end_h, end_m = parse_clock(shift_end)

          start = datetime(

                    day.year, day.month, day.day,

                    start_h, start_m, tzinfo=IST,

          )

          end = datetime(

                    day.year, day.month, day.day,

                    end_h, end_m, tzinfo=IST,

          )

          if end <= start:

                    end += timedelta(days=1)

          return end

def compute_late_minutes(

    punch_in: datetime,

    shift_start: str,

    attendance_day: Optional[str] = None,

) -> int:

    """Count whole elapsed minutes from shift start, only if over 10 minutes late."""

    local = to_ist(punch_in)

    hour, minute = parse_clock(shift_start)

    if attendance_day:

        shift_date = date.fromisoformat(attendance_day)

        expected = local.replace(

            year=shift_date.year,

            month=shift_date.month,

            day=shift_date.day,

            hour=hour,

            minute=minute,

            second=0,

            microsecond=0,

        )

    else:

        expected = local.replace(

            hour=hour,

            minute=minute,

            second=0,

            microsecond=0,

        )

    elapsed_seconds = (local - expected).total_seconds()

    if elapsed_seconds <= 600:

        return 0

    return max(0, math.floor(elapsed_seconds / 60))

def compute_work_hours(

          punch_in: datetime,

          punch_out: datetime,

) -> float:

          if to_utc(punch_out) < to_utc(punch_in):

                    raise HTTPException(422, "punch_out cannot be before punch_in")

          seconds = Decimal(

                    str((to_utc(punch_out) - to_utc(punch_in)).total_seconds())

          )

          hours = seconds / Decimal("3600")

          return float(

                    hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

          )

def compute_overtime(

          punch_out: datetime,

          shift_end: str,

          date_str: str,

          shift_start: str = "09:30",

) -> int:

          """Overtime is counted when at least 30 minutes past shift end."""

          end = shift_end_datetime(date_str, shift_start, shift_end)

          elapsed_seconds = (to_utc(punch_out) - end.astimezone(UTC)).total_seconds()

          if elapsed_seconds < 1800:

                    return 0

          return max(0, math.floor(elapsed_seconds / 60))

def calculate_half_day(

          work_hours: Optional[float],

) -> bool:

          """

          Default rule: a completed workday under 4 hours is a half-day.

          Verify this threshold against PROBLEM_STATEMENT.docx.

          """

          return work_hours is not None and work_hours < 4.50

# ---------------------------------------------------------------------------

# Request models

# ---------------------------------------------------------------------------

class EmployeeIn(BaseModel):

          model_config = ConfigDict(str_strip_whitespace=True)

          emp_code: str = Field(min_length=1, max_length=30)

          name: str = Field(min_length=1, max_length=150)

          email: str = Field(min_length=3, max_length=254)

          department: str = Field(min_length=1, max_length=100)

          shift_start: str = "09:30"

          shift_end: str = "18:30"

          joined_on: str

          @field_validator("shift_start", "shift_end")

          @classmethod

          def validate_shift_time(cls, value):

                    parse_clock(value)

                    return value

          @field_validator("joined_on")

          @classmethod

          def validate_joined_on(cls, value):

                    date.fromisoformat(value)

                    return value

class PunchInIn(BaseModel):

          emp_code: str = Field(min_length=1, max_length=30)

          punched_at: Optional[int] = Field(default=None, strict=True)

          status: str = "PRESENT"

          @field_validator("status")

          @classmethod

          def validate_status(cls, value):

                    value = value.upper()

                    if value not in {"PRESENT", "WFH", "ON_DUTY"}:
                              raise ValueError("Punch-in status must be PRESENT, WFH, or ON_DUTY")

                    return value

class PunchOutIn(BaseModel):

          emp_code: str = Field(min_length=1, max_length=30)

          punched_at: Optional[int] = Field(default=None, strict=True)

class AttendanceCorrectionIn(BaseModel):

          status: Optional[str] = None

          punch_in: Optional[int] = Field(default=None, strict=True)

          punch_out: Optional[int] = Field(default=None, strict=True)

          reason: Optional[str] = Field(default=None, max_length=500)

          @field_validator("status")

          @classmethod

          def validate_status(cls, value):

                    if value is None:

                              return value

                    value = value.upper()

                    if value not in {"PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"}:
                              raise ValueError("Unsupported attendance status")

                    return value

# ---------------------------------------------------------------------------

# Health

# ---------------------------------------------------------------------------

@app.get("/health")

def health():

    try:

        client.admin.command("ping")

        return {"status": "ok"}

    except PyMongoError:

        raise HTTPException(503, "MongoDB is unavailable")

# ---------------------------------------------------------------------------

# Employees

# ---------------------------------------------------------------------------

@app.post("/employees", status_code=201)

def create_employee(body: EmployeeIn):

          doc = body.model_dump()

          doc["created_at"] = now_utc()

          try:

                    result = db.employees.insert_one(doc)

          except DuplicateKeyError:

                    raise HTTPException(409, "emp_code already exists")

          return serialize_value(doc)

@app.get("/employees")

def list_employees(

          department: Optional[str] = None,

          page: int = Query(default=1, ge=1),

          page_size: int = Query(default=20, ge=1, le=100),

):

          query = {}

          if department:

                    query["department"] = department

          skip = (page - 1) * page_size

          total = db.employees.count_documents(query)

          items = list(

                    db.employees.find(query, {"_id": 0})

                    .sort("emp_code", ASCENDING)

                    .skip(skip)

                    .limit(page_size)

          )

          return paginated_result(

                    serialize_value(items), total, page, page_size

          )

# ---------------------------------------------------------------------------

# Punch in / punch out

# ---------------------------------------------------------------------------

@app.post("/attendance/punch-in", status_code=201)

def punch_in(body: PunchInIn):

          emp = get_employee(body.emp_code)

          ts = (

                    parse_epoch_ms(body.punched_at)

                    if body.punched_at is not None

                    else now_utc()

          )

          date_str = attendance_date(ts, emp["shift_start"], emp["shift_end"])

          # Store aware UTC datetimes. MongoDB persists timestamps as BSON dates.

          doc = {

                    "emp_code": body.emp_code,

                    "date": date_str,

                    "status": body.status,

                    "punch_in": ts,

                    "punch_out": None,

                    "work_hours": None,

                    "late_minutes": compute_late_minutes(ts, emp["shift_start"], date_str),

                    "overtime_minutes": 0,

                    "half_day": False,

                    "history": [],

          }

          try:

                    result = db.attendance_logs.insert_one(doc)

          except DuplicateKeyError:

                    raise HTTPException(

                              409,

                              "already punched in for this date",

                    )

          doc["_id"] = result.inserted_id

          return public_attendance(doc)

@app.post("/attendance/punch-out")

def punch_out(body: PunchOutIn):

    emp = get_employee(body.emp_code)

    ts = (

        parse_epoch_ms(body.punched_at)

        if body.punched_at is not None

        else now_utc()

    )

    # Find the latest attendance record for this employee

    # whose punch-in occurred at or before the punch-out time.

    doc = db.attendance_logs.find_one(

        {

            "emp_code": body.emp_code,

            "punch_in": {"$ne": None, "$lte": to_utc(ts)},

            "punch_out": None,

        },

        sort=[("punch_in", -1)],

    )

    if not doc:

        raise HTTPException(

            404,

            "No open punch-in record found for this employee",

        )

    date_str = doc["date"]

    if to_utc(ts) < to_utc(doc["punch_in"]):

        raise HTTPException(422, "punch_out cannot be before punch_in")

    work_hours = compute_work_hours(doc["punch_in"], ts)

    overtime = compute_overtime(

        ts,

        emp["shift_end"],

        date_str,

        emp["shift_start"],

    )

    update = {

        "$set": {

            "punch_out": ts,

            "work_hours": work_hours,

            "overtime_minutes": overtime,

            "half_day": calculate_half_day(work_hours),

        },

        "$push": {

            "history": {

                "action": "PUNCH_OUT",

                "at": now_utc(),

                "punch_out": ts,

            }

        },

    }

    result = db.attendance_logs.update_one(

        {

            "_id": doc["_id"],

            "punch_out": None,

        },

        update,

    )

    if result.modified_count == 0:

        raise HTTPException(409, "Attendance was modified concurrently")

    updated = db.attendance_logs.find_one({"_id": doc["_id"]})

    return public_attendance(updated)

# ---------------------------------------------------------------------------

# Attendance listing

# ---------------------------------------------------------------------------

@app.get("/attendance")

def list_attendance(

          emp_code: Optional[str] = None,

          date_from: Optional[str] = None,

          date_to: Optional[str] = None,

          status: Optional[str] = None,

          page: int = Query(default=1, ge=1),

          page_size: int = Query(default=20, ge=1, le=100),

):

          query = {}

          if emp_code:

                    query["emp_code"] = emp_code

          if date_from or date_to:

                    date_filter = {}

                    if date_from:

                              parse_date(date_from)

                              date_filter["$gte"] = date_from

                    if date_to:

                              parse_date(date_to)

                              date_filter["$lte"] = date_to

                    if date_from and date_to and date_from > date_to:

                              raise HTTPException(422, "date_from cannot be after date_to")

                    query["date"] = date_filter

          if status:

                    query["status"] = status.upper()

          skip = (page - 1) * page_size

          total = db.attendance_logs.count_documents(query)

          docs = list(

                    db.attendance_logs.find(query)

                    .sort("date", DESCENDING)

                    .skip(skip)

                    .limit(page_size)

          )

          return paginated_result(

                    [public_attendance(doc) for doc in docs],

                    total,

                    page,

                    page_size,

          )

# ---------------------------------------------------------------------------

# Manual attendance correction

# ---------------------------------------------------------------------------

@app.patch("/attendance/{emp_code}/{date_str}")

def correct_attendance(

          emp_code: str,

          date_str: str,

          body: AttendanceCorrectionIn,

):

          parse_date(date_str)

          get_employee(emp_code)

          doc = get_attendance(emp_code, date_str)

          changes = body.model_dump(exclude_unset=True, exclude={"reason"})

          if not changes:

                    raise HTTPException(422, "Provide at least one field to update")

          updated_values = {}

          if "status" in changes:

                    updated_values["status"] = changes["status"]

          punch_in_value = changes.get("punch_in")

          punch_out_value = changes.get("punch_out")

          new_punch_in = (

                    parse_epoch_ms(punch_in_value)

                    if punch_in_value is not None

                    else doc.get("punch_in")

          )

          new_punch_out = (

                    parse_epoch_ms(punch_out_value)

                    if punch_out_value is not None

                    else doc.get("punch_out")

          )

          if "punch_in" in changes:

                    updated_values["punch_in"] = new_punch_in

          if "punch_out" in changes:

                    updated_values["punch_out"] = new_punch_out

          if new_punch_in is not None and new_punch_out is not None:

                    if to_utc(new_punch_out) < to_utc(new_punch_in):

                              raise HTTPException(422, "punch_out cannot be before punch_in")

                    updated_values["work_hours"] = compute_work_hours(

                              new_punch_in, new_punch_out

                    )

                    updated_values["half_day"] = calculate_half_day(

                              updated_values["work_hours"]

                    )

          if new_punch_in is not None:

                    emp = get_employee(emp_code)

                    updated_values["late_minutes"] = compute_late_minutes(

                              new_punch_in, emp["shift_start"], date_str

                    )

          if new_punch_out is not None:

                    emp = get_employee(emp_code)

                    updated_values["overtime_minutes"] = compute_overtime(

                              new_punch_out,

                              emp["shift_end"],

                              date_str,

                              emp["shift_start"],

                    )

          history_entry = {

                    "action": "MANUAL_CORRECTION",

                    "at": now_utc(),

                    "reason": body.reason,

                    "before": {

                              key: doc.get(key)

                              for key in updated_values

                    },

                    "after": updated_values,

          }

          result = db.attendance_logs.update_one(

                    {"_id": doc["_id"]},

                    {

                              "$set": updated_values,

                              "$push": {"history": history_entry},

                    },

          )

          if result.matched_count == 0:

                    raise HTTPException(404, "Attendance record not found")

          return public_attendance(

                    db.attendance_logs.find_one({"_id": doc["_id"]})

          )

# ---------------------------------------------------------------------------

# Analytics: employee monthly summary

# ---------------------------------------------------------------------------

@app.get("/analytics/employees/{emp_code}/monthly")

def employee_monthly_analytics(

          emp_code: str,

          year: int = Query(ge=2000, le=2100),

          month: int = Query(ge=1, le=12),

):

          get_employee(emp_code)

          start = date(year, month, 1)

          next_month = (

                    date(year + 1, 1, 1)

                    if month == 12

                    else date(year, month + 1, 1)

          )

          docs = list(

                    db.attendance_logs.find({

                              "emp_code": emp_code,

                              "date": {

                                        "$gte": start.isoformat(),

                                        "$lt": next_month.isoformat(),

                              },

                    }).sort("date", ASCENDING)

          )

          present = sum(d.get("status") == "PRESENT" for d in docs)

          absent = sum(d.get("status") == "ABSENT" for d in docs)

          leave = sum(d.get("status") == "LEAVE" for d in docs)

          half_days = sum(

                    d.get("half_day", False) or d.get("status") == "HALF_DAY"

                    for d in docs

          )

          total_hours = round(

                    sum(float(d.get("work_hours") or 0) for d in docs), 2

          )

          total_late = sum(int(d.get("late_minutes") or 0) for d in docs)

          total_overtime = sum(

                    int(d.get("overtime_minutes") or 0) for d in docs

          )

          return {

                    "emp_code": emp_code,

                    "year": year,

                    "month": month,

                    "total_records": len(docs),

                    "present_days": present,

                    "absent_days": absent,

                    "leave_days": leave,

                    "half_days": half_days,

                    "total_work_hours": total_hours,

                    "total_late_minutes": total_late,

                    "total_overtime_minutes": total_overtime,

                    "attendance": [public_attendance(d) for d in docs],

          }

# ---------------------------------------------------------------------------

# Analytics: department summary

# ---------------------------------------------------------------------------

@app.get("/analytics/departments/summary")

def department_summary():

          employees = list(

                    db.employees.find(

                              {},

                              {"_id": 0, "emp_code": 1, "department": 1},

                    )

          )

          attendance = list(db.attendance_logs.find({}))

          employee_departments = {

                    emp["emp_code"]: emp.get("department", "Unknown")

                    for emp in employees

          }

          summary = {}

          for emp in employees:

                    department = emp.get("department", "Unknown")

                    summary.setdefault(

                              department,

                              {

                                        "department": department,

                                        "employee_count": 0,

                                        "attendance_records": 0,

                                        "present": 0,

                                        "absent": 0,

                                        "leave": 0,

                                        "half_days": 0,

                                        "work_hours": 0.0,

                                        "late_minutes": 0,

                                        "overtime_minutes": 0,

                              },

                    )

                    summary[department]["employee_count"] += 1

          for record in attendance:

                    department = employee_departments.get(

                              record["emp_code"], "Unknown"

                    )

                    entry = summary.setdefault(

                              department,

                              {

                                        "department": department,

                                        "employee_count": 0,

                                        "attendance_records": 0,

                                        "present": 0,

                                        "absent": 0,

                                        "leave": 0,

                                        "half_days": 0,

                                        "work_hours": 0.0,

                                        "late_minutes": 0,

                                        "overtime_minutes": 0,

                              },

                    )

                    entry["attendance_records"] += 1

                    entry["present"] += record.get("status") == "PRESENT"

                    entry["absent"] += record.get("status") == "ABSENT"

                    entry["leave"] += record.get("status") == "LEAVE"

                    entry["half_days"] += bool(record.get("half_day", False))

                    entry["work_hours"] += float(record.get("work_hours") or 0)

                    entry["late_minutes"] += int(record.get("late_minutes") or 0)

                    entry["overtime_minutes"] += int(

                              record.get("overtime_minutes") or 0

                    )

          results = sorted(summary.values(), key=lambda x: x["department"])

          for entry in results:

                    entry["work_hours"] = round(entry["work_hours"], 2)

          return {"departments": results, "total_departments": len(results)}

# ---------------------------------------------------------------------------

# Analytics: late-arrival leaderboard

# ---------------------------------------------------------------------------

@app.get("/analytics/leaderboard/late")

def late_arrival_leaderboard(

          date_from: Optional[str] = None,

          date_to: Optional[str] = None,

          limit: int = Query(default=10, ge=1, le=100),

):

          query = {"late_minutes": {"$gt": 0}}

          if date_from or date_to:

                    date_filter = {}

                    if date_from:

                              parse_date(date_from)

                              date_filter["$gte"] = date_from

                    if date_to:

                              parse_date(date_to)

                              date_filter["$lte"] = date_to

                    if date_from and date_to and date_from > date_to:

                              raise HTTPException(422, "date_from cannot be after date_to")

                    query["date"] = date_filter

          pipeline = [

                    {"$match": query},

                    {

                              "$group": {

                                        "_id": "$emp_code",

                                        "late_days": {"$sum": 1},

                                        "total_late_minutes": {"$sum": "$late_minutes"},

                              }

                    },

                    {

                              "$sort": {

                                        "total_late_minutes": -1,

                                        "late_days": -1,

                                        "_id": 1,

                              }

                    },

                    {"$limit": limit},

          ]

          results = list(db.attendance_logs.aggregate(pipeline))

          employee_codes = [item["_id"] for item in results]

          employee_docs = {

                    emp["emp_code"]: emp

                    for emp in db.employees.find(

                              {"emp_code": {"$in": employee_codes}},

                              {"_id": 0, "emp_code": 1, "name": 1, "department": 1},

                    )

          }

          leaderboard = []

          for rank, item in enumerate(results, start=1):

                    employee = employee_docs.get(item["_id"], {})

                    leaderboard.append({

                              "rank": rank,

                              "emp_code": item["_id"],

                              "name": employee.get("name"),

                              "department": employee.get("department"),

                              "late_days": item["late_days"],

                              "total_late_minutes": item["total_late_minutes"],

                    })

          return {"leaderboard": leaderboard}

# ---------------------------------------------------------------------------

# Analytics: department trend

# ---------------------------------------------------------------------------

@app.get("/analytics/departments/{department}/trend")

def department_trend(

          department: str,

          date_from: str,

          date_to: str,

):

          parse_date(date_from)

          parse_date(date_to)

          if date_from > date_to:

                    raise HTTPException(422, "date_from cannot be after date_to")

          employees = list(

                    db.employees.find(

                              {"department": department},

                              {"_id": 0, "emp_code": 1},

                    )

          )

          employee_codes = [emp["emp_code"] for emp in employees]

          if not employee_codes:

                    raise HTTPException(404, f"Department {department} not found")

          docs = list(

                    db.attendance_logs.find({

                              "emp_code": {"$in": employee_codes},

                              "date": {"$gte": date_from, "$lte": date_to},

                    }).sort("date", ASCENDING)

          )

          daily = {}

          for doc in docs:

                    day = doc["date"]

                    entry = daily.setdefault(

                              day,

                              {

                                        "date": day,

                                        "attendance_records": 0,

                                        "present": 0,

                                        "absent": 0,

                                        "leave": 0,

                                        "late_minutes": 0,

                                        "work_hours": 0.0,

                              },

                    )

                    entry["attendance_records"] += 1

                    entry["present"] += doc.get("status") == "PRESENT"

                    entry["absent"] += doc.get("status") == "ABSENT"

                    entry["leave"] += doc.get("status") == "LEAVE"

                    entry["late_minutes"] += int(doc.get("late_minutes") or 0)

                    entry["work_hours"] += float(doc.get("work_hours") or 0)

          trend = sorted(daily.values(), key=lambda item: item["date"])

          for entry in trend:

                    entry["work_hours"] = round(entry["work_hours"], 2)

          return {

                    "department": department,

                    "date_from": date_from,

                    "date_to": date_to,

                    "employee_count": len(employee_codes),

                    "trend": trend,

          }

# ---------------------------------------------------------------------------

# Admin: endpoint query-plan diagnostics

# ---------------------------------------------------------------------------


@app.get("/admin/explain/{endpoint}")
def explain_endpoint(endpoint: str):
    """Provide MongoDB query-plan diagnostics for supported operations."""

    supported = {
        "employees": {
            "collection": "employees",
            "filter": {},
            "sort": {"emp_code": 1},
            "description": "List employees ordered by employee code",
        },
        "attendance": {
            "collection": "attendance_logs",
            "filter": {},
            "sort": {"date": -1},
            "description": "List attendance ordered by date",
        },
        "employee_attendance": {
            "collection": "attendance_logs",
            "filter": {
                "emp_code": "EMP0001",
                "date": "2026-07-06",
            },
            "description": "Look up one employee's attendance for one day",
        },
        "late_leaderboard": {
            "collection": "attendance_logs",
            "filter": {"late_minutes": {"$gt": 0}},
            "description": "Find records with late arrivals",
        },
    }

    if endpoint not in supported:
        raise HTTPException(
            status_code=404,
            detail=(
                "Unsupported endpoint. Supported values: "
                + ", ".join(sorted(supported))
            ),
        )

    spec = supported[endpoint]
    collection = db[spec["collection"]]

    explain_command = {
        "find": spec["collection"],
        "filter": spec["filter"],
    }

    if "sort" in spec:
        explain_command["sort"] = spec["sort"]

    plan = db.command("explain", explain_command, verbosity="queryPlanner")

    return {
        "endpoint": endpoint,
        "collection": spec["collection"],
        "description": spec["description"],
        "query_plan": serialize_value(plan),
    }

# ---------------------------------------------------------------------------

# Graceful shutdown

# ---------------------------------------------------------------------------

@app.on_event("shutdown")

def close_mongo_connection():

          client.close()
