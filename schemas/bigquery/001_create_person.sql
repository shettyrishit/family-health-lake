-- Creates the person table.

CREATE TABLE IF NOT EXISTS `project-b01843b0-70b0-47d0-af0.health_os.person` (
  person_id STRING NOT NULL,
  display_name STRING,
  relationship STRING,
  date_of_birth DATE,
  sex STRING,
  active BOOL,
  notes STRING,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
);
