# REVIEW.md

List every defect you found in the starter `app/main.py` (helpers and endpoints). For each one:

| # | Where (function / line) | What is wrong | How you'd notice it (test, input, or symptom) | How you fixed it |
|---|---|---|---|---|
| 1 | health / 72-74 | Returns 200 without checking MongoDB connectivity. Should return 503 if MongoDB doesn't respond to ping. | Health check passes even when MongoDB is down. | Added MongoDB ping check with try/except. |
| 2 | create_employee / 77-85 | No unique index on emp_code, so concurrent duplicate creates can both succeed (race condition). | Two simultaneous POST /employees with same emp_code both return 201. | Created unique index on emp_code at startup. |
| 3 | create_employee / 82 | created_at is datetime, should be epoch milliseconds in response. | Response has datetime object instead of integer. | Convert datetime to epoch milliseconds before returning. |
| 4 | create_employee / 78-80 | No validation that shift_start != shift_end. | Can create employee with same start/end time. | Added validation in Pydantic model. |
| 5 | create_employee / 78-80 | No validation for emp_code pattern (EMP\d{4,6}). | Can create employee with invalid emp_code format. | Added pattern validation in Pydantic model. |
| 6 | list_employees / 93 | skip calculation is wrong: page * page_size instead of (page - 1) * page_size. | Page 1 skips 20 items instead of 0. | Fixed to (page - 1) * page_size. |
| 7 | list_employees / 94 | total counts all documents, not filtered set. | Total doesn't reflect department filter. | Changed to count_documents(q) with filter. |
| 8 | list_employees / 95 | Not sorted by emp_code ascending as required by spec. | Results in arbitrary order. | Added sort by emp_code ascending. |
| 9 | list_employees / 89 | No validation for page_size max 100. | Can request page_size=1000 which violates spec. | Added Pydantic validation. |
| 10 | punch_in / 101 | No 404 if employee not found. | Returns KeyError on unknown emp_code. | Added check and raise HTTPException(404). |
| 11 | punch_in / 102 | No validation for punched_at epoch milliseconds (rejects seconds-looking values < 100000000000). | Can send punched_at=1728000000 (seconds) and it's accepted. | Added validation for epoch millisecond range. |
| 12 | punch_in / 103 | Attendance date calculation doesn't use IST timezone (R1). | Date is local system date, not IST calendar date. | Convert to IST before calculating date. |
| 13 | punch_in / 103 | No overnight shift handling (R1). | Overnight shift punch-in gets wrong date. | Added overnight shift logic per R1. |
| 14 | punch_in / 102-103 | Instants not truncated to whole seconds (R1). | Microseconds stored in database. | Truncate to seconds before storing. |
| 15 | punch_in / 113 | compute_late_minutes doesn't handle IST timezone or overnight shifts. | Late minutes incorrect for overnight shifts. | Rewrote to handle IST and overnight shifts. |
| 16 | punch_in / 119 | Returns "id" field, but records have no id (addressed by emp_code+date). | Response includes unexpected "id" field. | Removed "id" field from response. |
| 17 | punch_in / 110 | punch_in is datetime in response, should be epoch milliseconds. | Response has datetime object. | Convert to epoch milliseconds. |
| 18 | punch_in / 109 | No validation for status (only PRESENT, WFH, ON_DUTY allowed). | Can punch in with ABSENT or LEAVE status. | Added enum validation in Pydantic model. |
| 19 | list_attendance / 144 | Loads entire collection into memory (violates spec). | Performance issue on ~100k records. | Use MongoDB sort/skip/limit instead. |
| 20 | list_attendance / 145 | Sorting in Python instead of MongoDB. | Inefficient and incorrect sorting. | Use MongoDB sort. |
| 21 | list_attendance / 146-147 | Pagination in Python instead of MongoDB. | Inefficient pagination. | Use MongoDB skip/limit. |
| 22 | list_attendance / 145 | Should sort by date descending, then emp_code ascending. | Only sorts by date. | Added secondary sort by emp_code. |
| 23 | list_attendance / 146 | total counts all docs then filters, should count with query. | Total is incorrect with filters. | Use count_documents(q). |
| 24 | list_attendance / 136-141 | No validation that date_from > date_to returns 422. | Invalid date range accepted. | Added validation. |
| 25 | list_attendance / 149 | Returns "id" field which shouldn't exist. | Response includes unexpected "id". | Removed "id" field. |
| 26 | list_attendance / 148 | punch_in/punch_out are datetime, should be epoch milliseconds. | Response has datetime objects. | Convert to epoch milliseconds. |
| 27 | compute_late_minutes / 33-37 | Doesn't handle IST timezone - compares naive datetime. | Incorrect late minutes in non-IST timezones. | Convert to IST before calculation. |
| 28 | compute_late_minutes / 36-37 | Doesn't handle overnight shifts. | Wrong late minutes for overnight shifts. | Added overnight shift logic. |
| 29 | compute_work_hours / 40-41 | Uses Python's round() which uses banker's rounding, not half-up (R4). | 9.125 rounds to 9.12 instead of 9.13. | Implemented half-up rounding. |
| 30 | compute_overtime / 44-47 | Incorrect date_str parsing - creates wrong datetime for shift_end. | Overtime calculation is wrong. | Fixed to calculate shift_end datetime properly. |
| 31 | compute_overtime / 47 | Doesn't check 30-minute minimum threshold (R3). | Overtime counted even if < 30 minutes. | Added threshold check. |
| 32 | compute_overtime / 44-47 | Doesn't handle overnight shifts. | Wrong overtime for overnight shifts. | Added overnight shift logic. |
| 33 | General / No startup | No indexes created at startup. | Queries use COLLSCAN, performance issues. | Added startup event to create indexes. |
| 34 | General / No models | Missing Pydantic models for request/response validation. | Invalid data accepted, incorrect response formats. | Created comprehensive Pydantic models. |
| 35 | General / No utilities | No epoch millisecond conversion utilities. | Inconsistent datetime handling. | Added helper functions for epoch<->datetime conversion. |
| 36 | General / No utilities | No IST timezone utilities. | Incorrect IST calculations. | Added IST conversion helpers. |

**Not a defect:**
- The basic structure with FastAPI and MongoDB connection is correct.
- The imports are appropriate for the project.
- The helper function signatures are reasonable placeholders.
