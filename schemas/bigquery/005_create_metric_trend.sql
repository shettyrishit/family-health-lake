CREATE TABLE IF NOT EXISTS `project-b01843b0-70b0-47d0-af0.health_os.metric_trend` (
                                                                                       trend_id STRING NOT NULL,
                                                                                       person_id STRING NOT NULL,
                                                                                       taxonomy STRING,
                                                                                       category STRING,
                                                                                       metric_name STRING,
                                                                                       trend_type STRING,
                                                                                       trend_summary STRING,
                                                                                       trend_status STRING,
                                                                                       start_date DATE,
                                                                                       end_date DATE,
                                                                                       related_metric_ids ARRAY<STRING>,
                                                                                       source_document_ids ARRAY<STRING>,
                                                                                       created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
);