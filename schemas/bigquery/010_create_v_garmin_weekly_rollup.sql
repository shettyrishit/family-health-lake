-- Creates a technical base view for Garmin weekly rollup metrics with trace.

CREATE OR REPLACE VIEW `project-b01843b0-70b0-47d0-af0.health_os.v_garmin_weekly_rollup` AS
SELECT
  m.person_id,
  COALESCE(o.document_id, m.document_id) AS document_id,
  m.metric_date AS week_start,
  m.metric_name,
  m.value,
  m.text_value,
  m.unit,
  m.status AS metric_status,
  o.taxonomy,
  o.observation_type,
  m.observation_id,
  o.raw_label,
  o.raw_value,
  o.source_location,
  COALESCE(o.notes, m.notes) AS notes,
  m.created_at
FROM `project-b01843b0-70b0-47d0-af0.health_os.health_metric` AS m
LEFT JOIN `project-b01843b0-70b0-47d0-af0.health_os.observation` AS o
  ON m.observation_id = o.observation_id
WHERE o.source = 'garmin_weekly_rollup';
