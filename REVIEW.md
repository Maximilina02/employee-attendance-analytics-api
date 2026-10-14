# REVIEW.md

## Defects found in `app/main.py`

| # | Where (function) | What is wrong | How you'd notice it (test, input, or symptom) | How you fixed it |
|---|---|---|---|---|
| 1 | `serialize_value()` | MongoDB BSON values such as `Timestamp` and binary data may not be JSON serializable. | Call the admin explain endpoint and inspect the response for serialization errors. | Added conversion for BSON `Timestamp`, binary data, lists, tuples, datetimes, and `ObjectId`. |
| 2 | `employee_monthly_analytics()` | The endpoint uses separate `year` and `month` parameters rather than the specified `YYYY-MM` month input. It also returns a different response structure from the contract. | Call the endpoint using the documented month format and compare the response fields with `openapi.yaml`. | Not fully fixed; the endpoint contract and response structure need alignment. |
| 3 | `employee_monthly_analytics()` | It fetches attendance documents and calculates totals in Python rather than using a MongoDB aggregation pipeline. | Inspect the database operations or test with a large attendance collection. | Not fixed; replace the Python calculations with a MongoDB aggregation pipeline. |
| 4 | `department_summary()` | It loads employees and attendance records into Python and aggregates them in application code instead of MongoDB. | Inspect database operations and test with a large dataset. | Not fixed; implement the required MongoDB aggregation while preserving employees with zero attendance records. |
| 5 | `department_summary()` | Its response does not include all required contract metrics, including the specified attendance percentage and other required summary fields. | Compare the response with the department-summary schema in `openapi.yaml`. | Not fully fixed; align the response fields and calculations with the contract. |
| 6 | `late_arrival_leaderboard()` | Ranking and cutoff handling need to be checked against the required tie-sharing behavior. Employees tied at the cutoff must not receive inconsistent ranks or be silently excluded if the contract requires shared ranks. | Create employees with equal late minutes around the `limit` boundary and inspect the returned ranks. | Not fully fixed; implement and test the specified tie-ranking and cutoff rules. |
| 7 | `department_trend()` | The endpoint calculates trends in Python and does not fully implement the required daily series and seven-day moving average. | Test a department with dates that have no attendance records and verify the returned daily values and moving averages. | Not fixed; implement the required MongoDB aggregation and complete calendar-day series. |
| 8 | `explain_endpoint()` | The endpoint names and explain-plan behavior do not fully match the required API contract. The current implementation uses `queryPlanner` rather than the required `executionStats`. | Call the documented endpoint names and inspect whether execution statistics are returned. | Not fully fixed; align supported endpoint names and use the required execution statistics. |
| 9 | `punch_out()` | The normal punch-out operation appends a `PUNCH_OUT` entry to the `history` array, which should be reserved for manual-correction audit entries under the assignment rules. | Punch out an employee and inspect the record's `history` array. | Not fixed; remove the history update from normal punch-out while retaining manual-correction auditing. |
| 10 | `correct_attendance()` | Manual corrections need stronger validation of the supplied fields and consistent recalculation of dependent attendance values. | Test corrections with invalid timestamps, incomplete punch pairs, and changed status values. | Not fully fixed; validate all correction cases and recalculate dependent fields consistently. |
| 11 | `compute_late_minutes()` | The ten-minute grace-period boundary and whole-minute calculation must match the stated business rule exactly. | Test a punch-in exactly ten minutes late and one ten minutes and one second late. | Added and ran boundary tests for the ten-minute grace period; verify the result against the specification. |
| 12 | `calculate_half_day()` | The half-day threshold must match the assignment's stated rule; the helper currently uses a threshold of 4.50 hours. | Test work durations immediately below, at, and above the specified threshold. | Added tests around the 4.50-hour boundary; confirm that this threshold matches the specification. |
| 13 | `compute_overtime()` | The overtime grace period and boundary behavior must match the specified minimum overtime rule. | Test punch-out times just before, exactly at, and after 30 minutes beyond shift end. | Added tests for the 30-minute overtime boundary; verify all edge cases against the specification. |

## Items reviewed and not considered defects

- The unique employee/date attendance index is appropriate for preventing duplicate attendance records for the same employee and date, provided duplicate-key errors are handled.
- Returning HTTP 409 for a duplicate punch-in is appropriate when the unique index rejects the insert.
- Rejecting a punch-out earlier than punch-in is appropriate validation.
- Using UTC for stored timestamps and converting them for local attendance calculations is a reasonable approach when applied consistently.
- Keeping a manual-correction reason and before/after values in the audit history is appropriate for traceability.
- The `/health` endpoint returning HTTP 200 confirms that the health route responds; it does not by itself prove that every API requirement is satisfied.

## Verification notes

Six automated attendance calculation tests passed locally. These tests cover selected grace-period, work-hour, half-day, and overtime calculations. They do not establish that every API contract, MongoDB aggregation, concurrency condition, or audit requirement is satisfied.

The remaining items above must be fixed and tested before they can be described as completed.
