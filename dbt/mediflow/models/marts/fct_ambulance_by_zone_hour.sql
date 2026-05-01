{{ config(unique_key=['hour_bucket', 'zone']) }}

select
    date_trunc('hour', dispatch_ts) as hour_bucket,
    zone,
    count(*) as dispatch_count,
    avg(response_minutes) as avg_response_minutes,
    percentile_cont(0.9) within group (order by response_minutes) as p90_response_minutes,
    avg(temp_c) as avg_temp_c,
    sum(precip_mm) as total_precip_mm
from {{ ref('stg_dispatch') }}
{% if is_incremental() %}
where dispatch_ts > (select coalesce(max(hour_bucket), '2024-01-01') from {{ this }}) - interval '48 hours'
{% endif %}
group by 1, 2
