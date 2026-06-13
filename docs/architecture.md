# Architecture decisions

## Data Flow
Generator / external pulls  
→ `raw` schema  
→ GE validation gate  
→ idempotent load into `warehouse` star schema (RLS, SCD2, partitioned)  
→ dbt builds `marts`  
→ DuckDB columnar copy for interactive slicing  
→ Superset dashboards (overlay forecast vs actual)  

The same marts feed model training, and predictions land in `ops.forecast_predictions`.


## Batch over streaming
Hospital operational decisions here run at hourly granularity; an hourly
micro-batch with a 48h late-data grace window delivers the same product as
Kafka/Flink at a fraction of the operational cost. Streaming is the wrong
trade on a $10/month VPS.

## DuckDB over ClickHouse
Single node, embedded, zero services to operate, reads Postgres in place via
the `postgres` extension, columnar scans cover every dashboard query pattern.
ClickHouse wins on multi-node ingest rates we will never reach.

## Superset over Grafana/Metabase/Streamlit
SQL-native semantic layer + RBAC + alert/report scheduler in one OSS package.
Grafana stays for infra metrics (its strength); Streamlit would mean
maintaining an app; Metabase's alerting and RBAC are thinner.

## Model-per-target
- **Prophet** (occupancy): bounded smooth rate, layered seasonalities,
  interpretable regressors, native PIs.
- **SARIMA** (ER wait): one dominant 24h cycle + autocorrelated shocks;
  auto_arima gives a defensible order-selection procedure.
- **LSTM** (ambulance): nonlinear hour x weekend x weather x recent-demand
  interactions; one week of hourly context (seq len 168).

Drift policy: rolling 7-day MAPE per model from `fct_forecast_vs_actual`;
breach of 15% branches the hourly DAG into retraining; new versions promote
only if holdout MAPE improves (champion/challenger in `ops.model_registry`).
