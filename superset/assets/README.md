# Superset asset bundle

Import after the stack is up and the Superset metadata DB is initialised:

```bash
cd superset/assets
zip -r ../mediflow_assets.zip .
docker compose exec superset superset import-assets -p /app/superset_home/mediflow_assets.zip --username admin
```

(Copy the zip into the container first: `docker compose cp ../mediflow_assets.zip superset:/app/superset_home/`.)

Then edit the `MediFlow Warehouse` database connection in Superset UI and
replace the masked password (XXXXXXXXXX) with the real one from Vault/.env.
Alert rules and thresholds: see `superset/alerts.md`.
