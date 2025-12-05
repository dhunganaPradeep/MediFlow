-- Audit log: who touched what, when, with row-level before/after images for
-- sensitive tables. Trigger-based so it cannot be bypassed by app code.

CREATE TABLE ops.audit_log (
    audit_id    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    db_user     TEXT NOT NULL DEFAULT current_user,
    app_user    TEXT,                                   -- SET app.user from Keycloak token
    client_addr INET DEFAULT inet_client_addr(),
    table_name  TEXT NOT NULL,
    operation   TEXT NOT NULL CHECK (operation IN ('INSERT','UPDATE','DELETE')),
    row_pk      TEXT,
    old_row     JSONB,
    new_row     JSONB
);
CREATE INDEX ix_audit_table_time ON ops.audit_log (table_name, occurred_at DESC);

CREATE OR REPLACE FUNCTION ops.fn_audit() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER AS $$
BEGIN
    INSERT INTO ops.audit_log (app_user, table_name, operation, row_pk, old_row, new_row)
    VALUES (
        current_setting('app.user', true),
        TG_TABLE_SCHEMA || '.' || TG_TABLE_NAME,
        TG_OP,
        COALESCE(
            CASE WHEN TG_OP = 'DELETE' THEN (to_jsonb(OLD) ->> 'patient_key')
                 ELSE (to_jsonb(NEW) ->> 'patient_key') END,
            'n/a'),
        CASE WHEN TG_OP IN ('UPDATE','DELETE') THEN to_jsonb(OLD) END,
        CASE WHEN TG_OP IN ('INSERT','UPDATE') THEN to_jsonb(NEW) END
    );
    RETURN COALESCE(NEW, OLD);
END $$;

CREATE TRIGGER trg_audit_dim_patient
    AFTER INSERT OR UPDATE OR DELETE ON warehouse.dim_patient
    FOR EACH ROW EXECUTE FUNCTION ops.fn_audit();

CREATE TRIGGER trg_audit_dim_staff
    AFTER INSERT OR UPDATE OR DELETE ON warehouse.dim_staff
    FOR EACH ROW EXECUTE FUNCTION ops.fn_audit();

-- Audit log is append-only, even for admins
REVOKE UPDATE, DELETE, TRUNCATE ON ops.audit_log FROM PUBLIC, mediflow_admin;
