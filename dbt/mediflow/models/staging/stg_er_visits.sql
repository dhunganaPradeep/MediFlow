select
    visit_id,
    source_record_id,
    time_key,
    hospital_key,
    patient_key,
    arrival_ts,
    triage_level,
    least(wait_minutes, 24 * 60)::numeric(7, 1) as wait_minutes,  -- cap dirty outliers at 24h
    left_without_seen
from {{ source('warehouse', 'fact_emergency_visits') }}
