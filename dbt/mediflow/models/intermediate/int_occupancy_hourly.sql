select
    u.snapshot_ts,
    u.time_key,
    h.hospital_id,
    h.region,
    d.department_id,
    d.name as department_name,
    u.beds_total,
    u.beds_occupied,
    u.staff_on_shift,
    round(u.beds_occupied::numeric / u.beds_total, 4) as occupancy_rate,
    round(u.beds_occupied::numeric / nullif(u.staff_on_shift, 0), 2) as patients_per_staff
from {{ ref('stg_utilization') }} u
join {{ source('warehouse', 'dim_hospital') }} h
    on h.hospital_key = u.hospital_key and h.is_current
join {{ source('warehouse', 'dim_department') }} d
    on d.department_key = u.department_key
