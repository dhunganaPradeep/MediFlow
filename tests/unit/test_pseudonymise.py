import pytest

from security.pseudonymise import pseudonymise_patient_id

pytestmark = pytest.mark.unit


def test_deterministic():
    assert pseudonymise_patient_id("MRN0000001") == pseudonymise_patient_id("MRN0000001")


def test_distinct_inputs_distinct_outputs():
    assert pseudonymise_patient_id("MRN0000001") != pseudonymise_patient_id("MRN0000002")


def test_output_is_hex_sha256():
    out = pseudonymise_patient_id("MRN0000001")
    assert len(out) == 64
    int(out, 16)  # raises if not hex


def test_no_mrn_leakage():
    assert "MRN0000001" not in pseudonymise_patient_id("MRN0000001")
