{{ config(unique_key=['hour_bucket', 'hospital_key']) }}

with hourly as (
    select
        date_trunc('hour', arrival_ts) as hour_bucket,
        hospital_key,
        count(*) as visit_count,
        avg(wait_minutes) as avg_wait_minutes,
        percentile_cont(0.9) within group (order by wait_minutes) as p90_wait_minutes
    from {{ ref('stg_er_visits') }}
    {% if is_incremental() %}
    where arrival_ts > (select coalesce(max(hour_bucket), '2024-01-01') from {{ this }}) - interval '8 days'
    {% endif %}
    group by 1, 2
)

select
    *,
    avg(avg_wait_minutes) over (
        partition by hospital_key
        order by hour_bucket
        rows between 167 preceding and current row  -- 7-day rolling at hourly grain
    ) as wait_7d_rolling_avg
from hourly
