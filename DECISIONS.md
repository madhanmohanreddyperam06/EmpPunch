# DECISIONS.md

1. **Indexes.** Which indexes did you create, and which query or guarantee does each one serve? Which one did you consider and rejected?

   I created 5 indexes at startup:
   - `employees.emp_code` (unique): Guarantees employee code uniqueness and enables efficient employee lookups. Required by the spec for concurrent duplicate create handling.
   - `attendance_logs.{emp_code, date}` (unique): Guarantees one record per employee per day and enables efficient punch-in duplicate detection.
   - `attendance_logs.date` (descending): Optimizes date range queries in attendance listing and analytics.
   - `attendance_logs.status`: Optimizes status filtering in attendance listing.
   - `attendance_logs.{date, status}`: Compound index for analytics queries that filter by both date and status.

   I considered adding an index on `employees.department` for department filtering, but rejected it because departments are likely few (small cardinality) and the query would still need to scan for headcount calculations. The existing compound indexes are sufficient for the main analytics aggregations.

2. **Punch-in race.** Two identical punch-in requests arrive at the same instant. Walk through exactly what happens in your code.

   When two identical punch-in requests arrive simultaneously:
   1. Both requests fetch the employee document (read operation, no conflict).
   2. Both requests calculate the attendance date and check for existing records using `find_one()`.
   3. Both requests attempt `insert_one()` with the same unique key `{emp_code, date}`.
   4. MongoDB's unique index guarantees atomicity: one insert succeeds, the other fails with `DuplicateKeyError`.
   5. The successful request returns 201 with the created record.
   6. The failed request catches the `DuplicateKeyError` and returns 409 with "already punched in for this date".

   This relies on the database's ACID guarantees rather than application-level check-then-insert, which would have a race condition.

3. **Ties.** Two employees are tied on late minutes at the cutoff of `limit`. What does your leaderboard return, and why?

   My leaderboard returns all employees whose rank is <= limit, including all tied employees at that rank. For example, if limit=10 and employees 10, 11, and 12 all have the same late_minutes, all three are returned even though that exceeds 10 rows.

   This follows the spec's requirement: "limit applies after ranking: return every employee whose rank <= limit. The response can therefore contain more than limit rows when employees tie at a rank <= limit."

   I use standard competition ranking (1, 2, 2, 4) where ties share a rank and the next rank is skipped. The response is sorted by total_late_minutes descending, then emp_code ascending for deterministic ordering within ties.

4. **Headcount.** How does your department summary make sure employees with zero logs are counted?

   The department summary calculates headcount by querying the `employees` collection with the condition `joined_on <= last_day_of_month`, independent of attendance logs. This ensures employees who joined but have no attendance records are still counted.

   Specifically:
   1. First, I get all distinct departments from employees who joined on or before the month's last day.
   2. For each department, I count employees using `count_documents({department, joined_on: {$lte: last_day}})`.
   3. Only then do I aggregate attendance logs for that department using the employee codes list.

   This separation ensures headcount is based on employee existence, not attendance activity, satisfying R9.

5. **One thing you would change** if this had to serve 100x the data.

   I would replace the individual document iteration in analytics (especially employee_monthly and department_summary) with pure MongoDB aggregations. Currently, some calculations like counting present_days on Mon-Fri only iterate through documents in Python after the initial aggregation. For 100x data (~10M records), this would be too slow.

   Instead, I would:
   - Use `$cond` within `$group` to filter Mon-Fri records during aggregation
   - Use `$densify` and `$fill` for gap-filling in trend calculations
   - Add more compound indexes for common query patterns
   - Consider sharding the attendance_logs collection by date or emp_code

   The current implementation works for ~100k records but would need optimization for millions.
