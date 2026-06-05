CREATE TABLE IF NOT EXISTS `project-b01843b0-70b0-47d0-af0.health_os.observation` (
                                                                                      observation_id STRING NOT NULL,
                                                                                      person_id STRING NOT NULL,
                                                                                      document_id STRING,
                                                                                      observed_at DATE,
                                                                                      source STRING,
                                                                                      taxonomy STRING,
                                                                                      observation_type STRING,
                                                                                      raw_label STRING,
                                                                                      raw_value STRING,
                                                                                      normalized_label STRING,
                                                                                      parsed_value FLOAT64,
                                                                                      unit STRING,
                                                                                      source_location STRING,
                                                                                      confidence FLOAT64,
                                                                                      conversion_status STRING,
                                                                                      notes STRING,
                                                                                      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
    );