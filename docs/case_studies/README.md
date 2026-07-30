# ACI case-study source documents

This folder retains the five case-study documents supplied for the ACI Knowledge
Assistant. They are evidence artifacts, not files exposed for upload in the public UI.

Retrieval-ready, source-attributed summaries are stored in `sample_data/aci`:

- `07_case_study_hospitality_data_intelligence.md`
- `08_case_study_sap_finance_transformation.md`
- `09_case_study_retail_loyalty_intelligence.md`
- `10_case_study_pds_data_platform.md`
- `11_case_study_shift_left_medical_device_security.md`

The summaries preserve important accuracy notes where a filename, anonymized client
description, official webpage, or metric version differs. At application startup, each
summary is embedded separately with OpenAI and indexed in MongoDB Atlas Vector Search.
