CREATE TABLE IF NOT EXISTS collector_scan (
    id smallint PRIMARY KEY CHECK (id = 1),
    revision bigint NOT NULL DEFAULT 0,
    scan_id uuid,
    source text CHECK (source IN ('manual', 'scheduler')),
    state text NOT NULL DEFAULT 'IDLE'
        CHECK (state IN ('IDLE', 'QUEUED', 'STARTING', 'RUNNING', 'FAILED', 'UNKNOWN')),
    apify_run_id varchar(255),
    updated_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO collector_scan (id) VALUES (1) ON CONFLICT (id) DO NOTHING;
