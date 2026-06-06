CREATE TABLE IF NOT EXISTS `project-b01843b0-70b0-47d0-af0.health_os.insight` (
                                                                                  insight_id STRING NOT NULL,
                                                                                  person_id STRING NOT NULL,
                                                                                  taxonomy STRING,
                                                                                  category STRING,
                                                                                  insight_type STRING,
                                                                                  summary STRING,
                                                                                  insight_status STRING,
                                                                                  supporting_metric_ids ARRAY<STRING>,
                                                                                  supporting_trend_ids ARRAY<STRING>,
                                                                                  supporting_alert_ids ARRAY<STRING>,
                                                                                  source_document_ids ARRAY<STRING>,
                                                                                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
);