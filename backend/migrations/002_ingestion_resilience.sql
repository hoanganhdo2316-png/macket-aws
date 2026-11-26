ALTER TABLE facebook_groups
    ADD COLUMN IF NOT EXISTS facebook_group_external_id varchar(255);

CREATE UNIQUE INDEX IF NOT EXISTS facebook_groups_external_id_unique
    ON facebook_groups (facebook_group_external_id)
    WHERE facebook_group_external_id IS NOT NULL;

ALTER TABLE crawl_runs
    ADD COLUMN IF NOT EXISTS skipped_posts integer NOT NULL DEFAULT 0;
