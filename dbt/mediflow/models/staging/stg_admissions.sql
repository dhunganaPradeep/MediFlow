with src as (
    select * from {{ source('warehouse', 'fact_admissions') }}
)

select
    admission_id,
    source_record_id,
    time_key,
    hospital_key,
    department_key,
    patient_key,
    diagnosis_key,
    admit_ts,
    discharge_ts,
    coalesce(los_hours, extract(epoch from (discharge_ts - admit_ts)) / 3600.0) as los_hours,
    is_readmission
from src
where admit_ts <= now()  -- guard against clock-skewed future records
