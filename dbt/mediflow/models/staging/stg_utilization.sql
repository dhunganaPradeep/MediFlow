select
    snapshot_id,
    time_key,
    hospital_key,
    department_key,
    snapshot_ts,
    beds_total,
    least(beds_occupied, beds_total) as beds_occupied,  -- physical bound
    staff_on_shift
from {{ source('warehouse', 'fact_resource_utilization') }}
where beds_total > 0
