CREATE TABLE IF NOT EXISTS `project-b01843b0-70b0-47d0-af0.health_os.alert` (
                                                                                alert_id STRING NOT NULL,
                                                                                person_id STRING NOT NULL,
                                                                                taxonomy STRING,
                                                                                category STRING,
                                                                                alert_type STRING,
                                                                                severity STRING,
                                                                                message STRING,
                                                                                status STRING,
                                                                                related_metric_ids ARRAY<STRING>,
                                                                                related_trend_ids ARRAY<STRING>,
                                                                                source_document_ids ARRAY<STRING>,
                                                                                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
);