{{ config(materialized='table') }}

select
    date_trunc('month', a.admit_ts) as month,
    dg.icd10_code,
    dg.description,
    dg.chapter,
    count(*) as admission_count,
    avg(a.los_hours) as avg_los_hours
from {{ ref('stg_admissions') }} a
join {{ source('warehouse', 'dim_diagnosis') }} dg on dg.diagnosis_key = a.diagnosis_key
group by 1, 2, 3, 4
