-- Creates the source_document table.

CREATE TABLE IF NOT EXISTS `project-b01843b0-70b0-47d0-af0.health_os.source_document` (
  document_id STRING NOT NULL,
  person_id STRING NOT NULL,
  document_type STRING,
  source STRING,
  document_date DATE,
  file_uri STRING,
  original_filename STRING,
  notes STRING,
  uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
);