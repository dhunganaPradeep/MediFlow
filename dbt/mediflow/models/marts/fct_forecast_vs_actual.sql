{{ config(materialized='table') }}

-- Joins latest predictions to realised occupancy: feeds dashboard forecast
-- overlays and the rolling-MAPE drift check that triggers retraining.
with latest_pred as (
    select distinct on (model_name, entity, forecast_ts)
        model_name, entity, forecast_ts, yhat, yhat_lower, yhat_upper
    from {{ source('ops', 'forecast_predictions') }}
    order by model_name, entity, forecast_ts, predicted_at desc
)

select
    p.model_name,
    p.entity,
    p.forecast_ts,
    p.yhat,
    p.yhat_lower,
    p.yhat_upper,
    o.occupancy_rate as actual,
    abs(p.yhat - o.occupancy_rate) / nullif(abs(o.occupancy_rate), 0) as ape
from latest_pred p
left join {{ ref('fct_occupancy_hourly') }} o
    on o.snapshot_ts = p.forecast_ts
    and o.department_id = p.entity
where p.model_name = 'prophet_occupancy'
