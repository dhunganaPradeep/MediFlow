{{ config(unique_key=['snapshot_ts', 'hospital_id', 'department_id']) }}

select
    o.*,
    t.hour,
    t.day_of_week,
    t.season,
    t.is_weekend,
    t.is_holiday,
    o.occupancy_rate >= 0.85 as is_capacity_alert
from {{ ref('int_occupancy_hourly') }} o
join {{ source('warehouse', 'dim_time') }} t on t.time_key = o.time_key

{% if is_incremental() %}
-- 48h lookback covers the late-arrival grace window (etl/late_data.py)
where o.snapshot_ts > (select coalesce(max(snapshot_ts), '2024-01-01') from {{ this }}) - interval '48 hours'
{% endif %}
