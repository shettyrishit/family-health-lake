-- Creates the first thyroid dashboard view with navigable trace.

CREATE OR REPLACE VIEW `project-b01843b0-70b0-47d0-af0.health_os.v_thyroid_dashboard` AS
WITH thyroid_insights AS (
  SELECT
    insight_id,
    person_id,
    summary AS insight_summary,
    insight_status,
    supporting_alert_ids,
    source_document_ids
  FROM `project-b01843b0-70b0-47d0-af0.health_os.insight`
  WHERE category = 'thyroid'
),
thyroid_alerts AS (
  SELECT
    alert_id,
    person_id,
    alert_type,
    message AS alert_message,
    severity AS alert_severity,
    related_trend_ids,
    related_metric_ids,
    source_document_ids
  FROM `project-b01843b0-70b0-47d0-af0.health_os.alert`
  WHERE category = 'thyroid'
),
thyroid_trends AS (
  SELECT
    trend_id,
    person_id,
    trend_summary,
    trend_status,
    source_document_ids
  FROM `project-b01843b0-70b0-47d0-af0.health_os.metric_trend`
  WHERE category = 'thyroid'
),
thyroid_metrics AS (
  SELECT
    metric_id,
    person_id,
    document_id,
    observation_id,
    metric_name,
    value,
    text_value,
    unit,
    reference_low,
    reference_high,
    status AS metric_status
  FROM `project-b01843b0-70b0-47d0-af0.health_os.health_metric`
  WHERE category = 'thyroid'
)
SELECT
  i.person_id,
  i.insight_id,
  i.insight_summary,
  i.insight_status,
  a.alert_id,
  a.alert_type,
  a.alert_message,
  a.alert_severity,
  t.trend_id,
  t.trend_summary,
  t.trend_status,
  m.metric_id,
  m.metric_name,
  m.value,
  m.text_value,
  m.unit,
  m.reference_low,
  m.reference_high,
  m.metric_status,
  o.observation_id,
  o.raw_label,
  o.raw_value,
  o.normalized_label,
  o.source_location,
  COALESCE(o.document_id, m.document_id, insight_document_id, alert_document_id, trend_document_id) AS document_id,
  sd.file_uri
FROM thyroid_insights AS i
LEFT JOIN UNNEST(IFNULL(i.supporting_alert_ids, [])) AS supporting_alert_id
LEFT JOIN UNNEST(IFNULL(i.source_document_ids, [])) AS insight_document_id
LEFT JOIN thyroid_alerts AS a
  ON a.alert_id = supporting_alert_id
  AND a.person_id = i.person_id
LEFT JOIN UNNEST(IFNULL(a.related_trend_ids, [])) AS related_trend_id
LEFT JOIN UNNEST(IFNULL(a.related_metric_ids, [])) AS related_metric_id
LEFT JOIN UNNEST(IFNULL(a.source_document_ids, [])) AS alert_document_id
LEFT JOIN thyroid_trends AS t
  ON t.trend_id = related_trend_id
  AND t.person_id = i.person_id
LEFT JOIN UNNEST(IFNULL(t.source_document_ids, [])) AS trend_document_id
LEFT JOIN thyroid_metrics AS m
  ON m.metric_id = related_metric_id
  AND m.person_id = i.person_id
LEFT JOIN `project-b01843b0-70b0-47d0-af0.health_os.observation` AS o
  ON o.observation_id = m.observation_id
  AND o.person_id = i.person_id
LEFT JOIN `project-b01843b0-70b0-47d0-af0.health_os.source_document` AS sd
  ON sd.document_id = COALESCE(o.document_id, m.document_id, insight_document_id, alert_document_id, trend_document_id)
  AND sd.person_id = i.person_id;
