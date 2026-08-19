# Running the governance test suite

Standard library only for the governance/execution code itself; `pytest`
is needed to run the tests.

```bash
pip install -r tests/governance/requirements.txt   # once, e.g. via Termux's pip
python3 -m pytest tests/governance -q
```

Every test gets isolated audit/approval/evidence/revocation storage (see
`tests/conftest.py`) -- none of them read or write the real,
repository-tracked `governance/*.jsonl` files. Test order never matters:
each test starts from empty governance state.

`test_nrm_incident.py::test_nrm_incident_full_regression` is the
permanent regression fixture for the incident that motivated this whole
package -- see `docs/evidence/NRM_TAG_403_CASE.md`.
