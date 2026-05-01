{% macro scd2_merge(target_table, source_table, natural_key, tracked_columns) %}
{#-
  SCD Type 2 merge:
  1. Close current rows whose row_hash changed (valid_to = now, is_current = false)
  2. Insert new versions for changed + brand-new natural keys
  Usage: {{ scd2_merge('warehouse.dim_hospital', 'raw.hospitals', 'hospital_id',
                       ['name', 'region', 'bed_capacity', 'trauma_level']) }}
-#}

with src as (
    select *,
        md5({% for c in tracked_columns %}coalesce({{ c }}::text, '') || '|' {% if not loop.last %}|| {% endif %}{% endfor %}) as row_hash
    from {{ source_table }}
),

changed as (
    update {{ target_table }} t
    set valid_to = now(), is_current = false
    from src s
    where t.{{ natural_key }} = s.{{ natural_key }}
      and t.is_current
      and t.row_hash <> s.row_hash
    returning t.{{ natural_key }}
)

insert into {{ target_table }} ({{ natural_key }}, {{ tracked_columns | join(', ') }}, row_hash, valid_from, valid_to, is_current)
select s.{{ natural_key }}, {% for c in tracked_columns %}s.{{ c }}{% if not loop.last %}, {% endif %}{% endfor %}, s.row_hash, now(), 'infinity', true
from src s
left join {{ target_table }} t
    on t.{{ natural_key }} = s.{{ natural_key }} and t.is_current
where t.{{ natural_key }} is null
{% endmacro %}
