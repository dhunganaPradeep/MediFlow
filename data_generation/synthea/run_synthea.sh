#!/usr/bin/env bash
# Optional realistic-data path: Synthea synthetic patient generator.
# Produces 100k patients with modules relevant to demand forecasting.
set -euo pipefail

if [ ! -d synthea ]; then
  git clone --depth 1 https://github.com/synthetichealth/synthea.git
fi
cd synthea

./run_synthea -p 100000 \
  --exporter.csv.export=true \
  --exporter.fhir.export=false \
  --generate.only_alive_patients=true \
  -m "flu*;covid19;asthma;copd;heart*;injuries;appendicitis;urinary_tract_infections" \
  Massachusetts

# Output lands in synthea/output/csv/: patients.csv, encounters.csv,
# conditions.csv, observations.csv. Map encounters -> raw.admissions,
# conditions -> dim_diagnosis via etl/extract/synthea_loader (ICD-10 mapping).
echo "Done. CSVs in synthea/output/csv/"
