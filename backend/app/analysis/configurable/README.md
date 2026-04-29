# Configurable analysis axes

Universal dimensions (in `../universal/`) ship as part of `PostCallAnalysis` and
run for every client. Configurable dimensions live here as opt-in
`AxisFieldDef` definitions that a client appends to
`ExtractionConfig.extra_axes` — typically through a future client config UI.

`insurance.py::CURRENT_INSURANCE_FIELD` is the canonical example. The Lead
model still owns `current_insurance` as a column populated by conversation
tools, but the LLM no longer extracts it by default. An insurance vertical can
re-enable extraction by adding `CURRENT_INSURANCE_FIELD` to its
`ExtractionConfig.extra_axes`.
