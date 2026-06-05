-- Creates the health_metric table.

CREATE TABLE IF NOT EXISTS `project-b01843b0-70b0-47d0-af0.health_os.health_metric` (
  metric_id STRING NOT NULL,
  person_id STRING NOT NULL,
  document_id STRING,
  metric_date DATE NOT NULL,
  source STRING,
  category STRING,
  metric_name STRING NOT NULL,
  value FLOAT64,
  text_value STRING,
  unit STRING,
  reference_low FLOAT64,
  reference_high FLOAT64,
  status STRING,
  notes STRING,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
);