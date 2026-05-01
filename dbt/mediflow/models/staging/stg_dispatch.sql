select
    dispatch_id,
    source_record_id,
    time_key,
    hospital_key,
    dispatch_ts,
    zone,
    priority,
    response_minutes,
    temp_c,
    precip_mm
from {{ source('warehouse', 'fact_ambulance_dispatch') }}
