-- Row-level security: admin sees all, analyst is region-scoped via session
-- setting `app.region` (set by Superset/ETL after Keycloak auth), viewer can
-- only read marts (no direct fact access).

CREATE ROLE mediflow_admin   NOLOGIN;
CREATE ROLE mediflow_analyst NOLOGIN;
CREATE ROLE mediflow_viewer  NOLOGIN;

GRANT USAGE ON SCHEMA warehouse, marts, ops TO mediflow_admin;
GRANT USAGE ON SCHEMA warehouse, marts      TO mediflow_analyst;
GRANT USAGE ON SCHEMA marts                 TO mediflow_viewer;

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA warehouse, ops TO mediflow_admin;
GRANT SELECT ON ALL TABLES IN SCHEMA warehouse TO mediflow_analyst;
GRANT SELECT ON ALL TABLES IN SCHEMA marts TO mediflow_admin, mediflow_analyst, mediflow_viewer;
ALTER DEFAULT PRIVILEGES IN SCHEMA marts GRANT SELECT TO mediflow_admin, mediflow_analyst, mediflow_viewer;

-- Analysts never see encrypted quasi-identifiers
REVOKE SELECT (zip3_enc, birth_year_enc) ON warehouse.dim_patient FROM mediflow_analyst;

DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['fact_admissions','fact_emergency_visits','fact_resource_utilization','fact_ambulance_dispatch'] LOOP
        EXECUTE format('ALTER TABLE warehouse.%I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('CREATE POLICY p_admin_all_%s ON warehouse.%I FOR ALL TO mediflow_admin USING (true) WITH CHECK (true)', t, t);
        EXECUTE format($f$
            CREATE POLICY p_analyst_region_%s ON warehouse.%I FOR SELECT TO mediflow_analyst
            USING (
                hospital_key IS NULL OR hospital_key IN (
                    SELECT hospital_key FROM warehouse.dim_hospital
                    WHERE region = current_setting('app.region', true)
                )
            )$f$, t, t);
    END LOOP;
END $$;
