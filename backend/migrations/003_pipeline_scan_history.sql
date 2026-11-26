-- Link only future ingestions to their scan and crawl run. Historical rows remain untouched.
ALTER TABLE crawl_runs
    ADD COLUMN IF NOT EXISTS scan_id uuid,
    ADD COLUMN IF NOT EXISTS source varchar(30);

ALTER TABLE posts
    ADD COLUMN IF NOT EXISTS crawl_run_id bigint;

CREATE INDEX IF NOT EXISTS crawl_runs_scan_id_idx ON crawl_runs (scan_id) WHERE scan_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS posts_crawl_run_id_idx ON posts (crawl_run_id) WHERE crawl_run_id IS NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'posts_crawl_run_id_fkey') THEN
        ALTER TABLE posts ADD CONSTRAINT posts_crawl_run_id_fkey FOREIGN KEY (crawl_run_id) REFERENCES crawl_runs(id);
    END IF;
END $$;
