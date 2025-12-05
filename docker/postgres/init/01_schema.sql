-- MediFlow star schema. Runs once at container init.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS raw;        -- landing zone, loaded by ETL
CREATE SCHEMA IF NOT EXISTS warehouse;  -- star schema
CREATE SCHEMA IF NOT EXISTS marts;      -- dbt-built marts
CREATE SCHEMA IF NOT EXISTS ops;        -- DLQ, watermarks, audit, model registry

SET search_path TO warehouse, public;

-- ---------------------------------------------------------------- dim_time
CREATE TABLE dim_time (
    time_key      INTEGER PRIMARY KEY,                -- YYYYMMDDHH
    ts            TIMESTAMPTZ NOT NULL UNIQUE,
    hour          SMALLINT NOT NULL CHECK (hour BETWEEN 0 AND 23),
    day           SMALLINT NOT NULL CHECK (day BETWEEN 1 AND 31),
    day_of_week   SMALLINT NOT NULL CHECK (day_of_week BETWEEN 0 AND 6), -- 0=Mon
    week          SMALLINT NOT NULL CHECK (week BETWEEN 1 AND 53),
    month         SMALLINT NOT NULL CHECK (month BETWEEN 1 AND 12),
    season        TEXT NOT NULL CHECK (season IN ('winter','spring','summer','autumn')),
    is_holiday    BOOLEAN NOT NULL DEFAULT FALSE,
    is_weekend    BOOLEAN NOT NULL DEFAULT FALSE
);

-- Populate hourly grain 2024-2027
INSERT INTO dim_time
SELECT
    (to_char(ts, 'YYYYMMDDHH24'))::int,
    ts,
    EXTRACT(hour FROM ts)::smallint,
    EXTRACT(day FROM ts)::smallint,
    EXTRACT(isodow FROM ts)::smallint - 1,
    EXTRACT(week FROM ts)::smallint,
    EXTRACT(month FROM ts)::smallint,
    CASE
        WHEN EXTRACT(month FROM ts) IN (12,1,2) THEN 'winter'
        WHEN EXTRACT(month FROM ts) IN (3,4,5)  THEN 'spring'
        WHEN EXTRACT(month FROM ts) IN (6,7,8)  THEN 'summer'
        ELSE 'autumn'
    END,
    FALSE,  -- holidays flagged by ETL via python `holidays` package
    EXTRACT(isodow FROM ts) IN (6,7)
FROM generate_series('2024-01-01'::timestamptz, '2027-12-31 23:00'::timestamptz, '1 hour') AS ts;

-- ------------------------------------------------------ dim_hospital (SCD2)
CREATE TABLE dim_hospital (
    hospital_key  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    hospital_id   TEXT NOT NULL,                       -- natural key
    name          TEXT NOT NULL,
    region        TEXT NOT NULL,
    bed_capacity  INTEGER NOT NULL CHECK (bed_capacity > 0),
    trauma_level  SMALLINT CHECK (trauma_level BETWEEN 1 AND 5),
    row_hash      TEXT NOT NULL,                       -- md5 of tracked attrs, drives SCD2
    valid_from    TIMESTAMPTZ NOT NULL DEFAULT now(),
    valid_to      TIMESTAMPTZ NOT NULL DEFAULT 'infinity',
    is_current    BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE UNIQUE INDEX uq_dim_hospital_current ON dim_hospital (hospital_id) WHERE is_current;
CREATE INDEX ix_dim_hospital_region ON dim_hospital (region) WHERE is_current;

-- --------------------------------------------------------- dim_staff (SCD2)
CREATE TABLE dim_staff (
    staff_key     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    staff_id      TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('physician','nurse','paramedic','technician','admin')),
    seniority     TEXT NOT NULL CHECK (seniority IN ('junior','mid','senior')),
    fte           NUMERIC(3,2) NOT NULL CHECK (fte > 0 AND fte <= 1),
    department_id TEXT NOT NULL,
    row_hash      TEXT NOT NULL,
    valid_from    TIMESTAMPTZ NOT NULL DEFAULT now(),
    valid_to      TIMESTAMPTZ NOT NULL DEFAULT 'infinity',
    is_current    BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE UNIQUE INDEX uq_dim_staff_current ON dim_staff (staff_id) WHERE is_current;

-- ----------------------------------------------------------- dim_department
CREATE TABLE dim_department (
    department_key BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    department_id  TEXT NOT NULL UNIQUE,
    name           TEXT NOT NULL,
    specialty      TEXT NOT NULL,
    bed_count      INTEGER NOT NULL CHECK (bed_count >= 0)
);

-- ---------------------------------------------- dim_patient (pseudonymised)
-- patient_pseudo_id = HMAC-SHA256(source MRN, key from Vault). No direct PII.
-- zip3 and birth_year are quasi-identifiers -> encrypted at rest via pgcrypto.
CREATE TABLE dim_patient (
    patient_key       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    patient_pseudo_id TEXT NOT NULL UNIQUE,
    sex               TEXT CHECK (sex IN ('F','M','O')),
    age_band          TEXT NOT NULL CHECK (age_band IN ('0-17','18-39','40-64','65-79','80+')),
    zip3_enc          BYTEA,   -- pgp_sym_encrypt(zip3, app.enc_key)
    birth_year_enc    BYTEA    -- pgp_sym_encrypt(birth_year::text, app.enc_key)
);

-- Encryption helpers: key injected per-session via SET app.enc_key (from Vault)
CREATE OR REPLACE FUNCTION warehouse.enc(val TEXT) RETURNS BYTEA
LANGUAGE sql AS $$ SELECT pgp_sym_encrypt(val, current_setting('app.enc_key'), 'cipher-algo=aes256') $$;

CREATE OR REPLACE FUNCTION warehouse.dec(val BYTEA) RETURNS TEXT
LANGUAGE sql AS $$ SELECT pgp_sym_decrypt(val, current_setting('app.enc_key')) $$;

-- ------------------------------------------------------------ dim_diagnosis
CREATE TABLE dim_diagnosis (
    diagnosis_key BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    icd10_code    TEXT NOT NULL UNIQUE,
    description   TEXT NOT NULL,
    chapter       TEXT NOT NULL,                        -- ICD-10 chapter grouping
    is_chronic    BOOLEAN NOT NULL DEFAULT FALSE
);

-- ---------------------------------------------------------- fact_admissions
CREATE TABLE fact_admissions (
    admission_id     BIGINT GENERATED ALWAYS AS IDENTITY,
    batch_id         UUID NOT NULL,                     -- idempotency token
    source_record_id TEXT NOT NULL,                     -- natural key from source
    time_key         INTEGER NOT NULL REFERENCES dim_time (time_key),
    hospital_key     BIGINT NOT NULL REFERENCES dim_hospital (hospital_key),
    department_key   BIGINT NOT NULL REFERENCES dim_department (department_key),
    patient_key      BIGINT NOT NULL REFERENCES dim_patient (patient_key),
    diagnosis_key    BIGINT NOT NULL REFERENCES dim_diagnosis (diagnosis_key),
    admit_ts         TIMESTAMPTZ NOT NULL,
    discharge_ts     TIMESTAMPTZ,
    los_hours        NUMERIC(8,2) CHECK (los_hours IS NULL OR los_hours >= 0),
    is_readmission   BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (admission_id, admit_ts),
    UNIQUE (source_record_id, admit_ts)                 -- rerun-safe upserts
) PARTITION BY RANGE (admit_ts);

-- --------------------------------------------------- fact_emergency_visits
CREATE TABLE fact_emergency_visits (
    visit_id         BIGINT GENERATED ALWAYS AS IDENTITY,
    batch_id         UUID NOT NULL,
    source_record_id TEXT NOT NULL,
    time_key         INTEGER NOT NULL REFERENCES dim_time (time_key),
    hospital_key     BIGINT NOT NULL REFERENCES dim_hospital (hospital_key),
    patient_key      BIGINT NOT NULL REFERENCES dim_patient (patient_key),
    diagnosis_key    BIGINT REFERENCES dim_diagnosis (diagnosis_key),
    arrival_ts       TIMESTAMPTZ NOT NULL,
    triage_level     SMALLINT NOT NULL CHECK (triage_level BETWEEN 1 AND 5),
    wait_minutes     NUMERIC(7,1) NOT NULL CHECK (wait_minutes >= 0),
    left_without_seen BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (visit_id, arrival_ts),
    UNIQUE (source_record_id, arrival_ts)
) PARTITION BY RANGE (arrival_ts);

-- ------------------------------------------------ fact_resource_utilization
-- Hourly snapshot grain per hospital x department.
CREATE TABLE fact_resource_utilization (
    snapshot_id    BIGINT GENERATED ALWAYS AS IDENTITY,
    batch_id       UUID NOT NULL,
    time_key       INTEGER NOT NULL REFERENCES dim_time (time_key),
    hospital_key   BIGINT NOT NULL REFERENCES dim_hospital (hospital_key),
    department_key BIGINT NOT NULL REFERENCES dim_department (department_key),
    snapshot_ts    TIMESTAMPTZ NOT NULL,
    beds_total     INTEGER NOT NULL CHECK (beds_total >= 0),
    beds_occupied  INTEGER NOT NULL CHECK (beds_occupied >= 0),
    staff_on_shift INTEGER NOT NULL CHECK (staff_on_shift >= 0),
    ventilators_in_use INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (snapshot_id, snapshot_ts),
    UNIQUE (hospital_key, department_key, snapshot_ts)  -- one snapshot per hour
) PARTITION BY RANGE (snapshot_ts);

-- --------------------------------------------------- fact_ambulance_dispatch
CREATE TABLE fact_ambulance_dispatch (
    dispatch_id      BIGINT GENERATED ALWAYS AS IDENTITY,
    batch_id         UUID NOT NULL,
    source_record_id TEXT NOT NULL,
    time_key         INTEGER NOT NULL REFERENCES dim_time (time_key),
    hospital_key     BIGINT REFERENCES dim_hospital (hospital_key),
    dispatch_ts      TIMESTAMPTZ NOT NULL,
    zone             TEXT NOT NULL,
    priority         SMALLINT NOT NULL CHECK (priority BETWEEN 1 AND 3),
    response_minutes NUMERIC(6,1) NOT NULL CHECK (response_minutes >= 0),
    temp_c           NUMERIC(4,1),                      -- weather at dispatch
    precip_mm        NUMERIC(5,1),
    PRIMARY KEY (dispatch_id, dispatch_ts),
    UNIQUE (source_record_id, dispatch_ts)
) PARTITION BY RANGE (dispatch_ts);

-- ------------------------------------------- monthly partitions 2025..2026
DO $$
DECLARE
    t TEXT;
    d DATE;
BEGIN
    FOREACH t IN ARRAY ARRAY['fact_admissions','fact_emergency_visits','fact_resource_utilization','fact_ambulance_dispatch'] LOOP
        d := '2025-01-01';
        WHILE d < '2027-01-01' LOOP
            EXECUTE format(
                'CREATE TABLE IF NOT EXISTS warehouse.%I_%s PARTITION OF warehouse.%I FOR VALUES FROM (%L) TO (%L)',
                t, to_char(d, 'YYYYMM'), t, d, d + INTERVAL '1 month');
            d := d + INTERVAL '1 month';
        END LOOP;
        EXECUTE format('CREATE TABLE IF NOT EXISTS warehouse.%I_default PARTITION OF warehouse.%I DEFAULT', t, t);
    END LOOP;
END $$;

-- ------------------------------------------------------------------ indexes
-- Query patterns: time-windowed aggregations by department/hospital/zone.
CREATE INDEX ix_adm_time_dept   ON fact_admissions (time_key, department_key);
CREATE INDEX ix_adm_admit_brin  ON fact_admissions USING brin (admit_ts);
CREATE INDEX ix_er_time_hosp    ON fact_emergency_visits (time_key, hospital_key);
CREATE INDEX ix_er_arrival_brin ON fact_emergency_visits USING brin (arrival_ts);
CREATE INDEX ix_util_dept_ts    ON fact_resource_utilization (department_key, snapshot_ts);
CREATE INDEX ix_util_brin       ON fact_resource_utilization USING brin (snapshot_ts);
CREATE INDEX ix_amb_zone_ts     ON fact_ambulance_dispatch (zone, dispatch_ts);
CREATE INDEX ix_amb_brin        ON fact_ambulance_dispatch USING brin (dispatch_ts);

-- --------------------------------------------------------------- ops tables
CREATE TABLE ops.dead_letter_queue (
    dlq_id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_table  TEXT NOT NULL,
    batch_id      UUID NOT NULL,
    payload       JSONB NOT NULL,
    error_reason  TEXT NOT NULL,
    failed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    replayed_at   TIMESTAMPTZ,
    replay_status TEXT CHECK (replay_status IN ('pending','succeeded','failed_again'))
        DEFAULT 'pending'
);
CREATE INDEX ix_dlq_pending ON ops.dead_letter_queue (source_table) WHERE replay_status = 'pending';

CREATE TABLE ops.etl_watermarks (
    source_table TEXT PRIMARY KEY,
    high_water   TIMESTAMPTZ NOT NULL,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE ops.model_registry (
    model_id    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    model_name  TEXT NOT NULL,          -- prophet_occupancy | sarima_er_wait | lstm_ambulance
    version     TEXT NOT NULL,
    trained_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    metrics     JSONB NOT NULL,         -- {rmse, mape, pi_coverage}
    artifact_path TEXT NOT NULL,
    is_active   BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (model_name, version)
);

CREATE TABLE ops.forecast_predictions (
    prediction_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    model_name    TEXT NOT NULL,
    target        TEXT NOT NULL,
    entity        TEXT NOT NULL,        -- department_id / hospital_id / zone
    forecast_ts   TIMESTAMPTZ NOT NULL,
    predicted_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    yhat          NUMERIC NOT NULL,
    yhat_lower    NUMERIC,
    yhat_upper    NUMERIC,
    UNIQUE (model_name, entity, forecast_ts, predicted_at)
);
CREATE INDEX ix_pred_lookup ON ops.forecast_predictions (model_name, entity, forecast_ts DESC);
