# Alert rules (configured as Superset SQL alerts; runs every 10 min)

| Alert | SQL condition | Threshold | Delivery |
|---|---|---|---|
| Capacity breach | `SELECT count(*) FROM marts.fct_occupancy_hourly WHERE snapshot_ts >= now() - interval '1 hour' AND occupancy_rate >= 0.85` | count > 0 | Slack #hospital-ops + email ops-admin |
| Critical capacity | same, `>= 0.95` | count > 0 | Slack @channel + email ops-admin, er-coordinator |
| ER wait spike | `SELECT max(avg_wait_minutes / nullif(wait_7d_rolling_avg,0)) FROM marts.fct_er_wait_rolling WHERE hour_bucket >= now() - interval '2 hours'` | ratio > 1.5 | Slack #er-response |
| Predicted surge (4h) | `SELECT max(yhat_upper) FROM ops.forecast_predictions WHERE model_name='prophet_occupancy' AND forecast_ts BETWEEN now() AND now() + interval '4 hours'` | > 0.90 | Slack #er-response + email er-coordinator |
| Forecast drift | `SELECT avg(ape) FROM marts.fct_forecast_vs_actual WHERE forecast_ts >= now() - interval '7 days'` | > 0.15 | Slack #data-eng (retrain DAG fires automatically) |
| Ambulance response degradation | `SELECT max(p90_response_minutes) FROM marts.fct_ambulance_by_zone_hour WHERE hour_bucket >= now() - interval '3 hours'` | > 20 | Slack #er-response |

Dashboards (exported JSON to be added under superset/dashboards/ after first
`superset import-dashboards` round-trip):

1. **Hospital Operations** (ops-admin): occupancy gauges per department,
   24h admission trend + forecast overlay (fct_forecast_vs_actual),
   staff-shortage heatmap (v_staff_ratio_by_shift), >85% alert table.
2. **Emergency Response** (er-coordinator): live ER queue depth, wait vs
   7-day average, ambulance availability by zone, 4h surge prediction band.
3. **Strategic Planning** (health-planner): 30-day demand forecast by
   department, seasonal capacity gap, utilization efficiency score,
   MoM admissions by diagnosis (fct_admissions_by_diagnosis_month).
