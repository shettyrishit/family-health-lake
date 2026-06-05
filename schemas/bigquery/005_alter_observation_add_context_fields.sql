ALTER TABLE `project-b01843b0-70b0-47d0-af0.health_os.observation`
    ADD COLUMN IF NOT EXISTS raw_text STRING,
    ADD COLUMN IF NOT EXISTS surrounding_text STRING,
    ADD COLUMN IF NOT EXISTS failure_reason STRING;
