# DECISIONS.md

## 1. Indexes

I use a unique compound index on employee ID and attendance date to prevent duplicate attendance records for the same employee on the same day. This also supports attendance lookups by employee and date. I would consider an additional index on department and attendance date for department analytics, but I would measure query performance before adding it.

## 2. Punch-in race

If two identical punch-in requests arrive simultaneously, both may initially find no attendance record. The unique compound index is the final protection against duplicate records. One insert succeeds, while the other should receive a duplicate-key error and return a conflict response. The application must handle that error explicitly.

## 3. Ties

The leaderboard must handle employees with equal late minutes consistently. If two employees tie at the cutoff, the response should follow the specified ranking rule and should not silently exclude a tied employee. The current implementation needs verification against this requirement.

## 4. Headcount

Department headcount should come from the employees collection, not only from attendance records. This ensures employees with no attendance logs are still counted. A suitable aggregation can start with employees and join attendance data.

## 5. Scaling to 100x data

I would move analytics calculations into MongoDB aggregation pipelines, add indexes based on measured query patterns, and test performance with a larger dataset. I would also review pagination and query execution statistics to identify expensive operations.