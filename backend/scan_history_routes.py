from fastapi import APIRouter, Depends, Query
from sqlalchemy import text

from admin_routes import verify_admin

router = APIRouter(prefix="/api/admin/scan-history", tags=["Scan History"], dependencies=[Depends(verify_admin)])


def register_scan_history_routes(app, engine):
    @router.get("")
    def list_scan_history(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
        with engine.connect() as conn:
            total = conn.execute(text("SELECT COUNT(*) FROM crawl_runs")).scalar_one()
            rows = conn.execute(text("""
                SELECT r.id, r.scan_id, r.source, r.apify_run_id, r.apify_dataset_id,
                       r.status, r.total_posts, r.inserted_posts, r.duplicate_posts,
                       r.skipped_posts, r.error_message, r.started_at, r.finished_at,
                       COUNT(p.id) AS linked_posts,
                       COUNT(c.id) AS classified_posts,
                       COUNT(p.id) FILTER (WHERE c.id IS NULL AND p.content IS NOT NULL
                         AND LENGTH(TRIM(p.content)) >= 10 AND NOT EXISTS (
                             SELECT 1 FROM author_skip_list a WHERE a.skip_enabled = TRUE
                             AND (a.facebook_author_id = p.author_id OR a.profile_url = p.author_url)
                         ) AND NOT EXISTS (
                             SELECT 1 FROM stage1_claims sc WHERE sc.post_id = p.id
                             AND sc.prompt_version_id = 7
                         )) AS classification_pending,
                       COUNT(p.id) FILTER (WHERE EXISTS (
                           SELECT 1 FROM stage1_claims sc WHERE sc.post_id = p.id
                           AND sc.prompt_version_id = 7 AND sc.status = 'processing'
                       )) AS classification_processing,
                       COUNT(c.id) FILTER (WHERE c.seller_type = 'individual') AS individual_posts,
                       COUNT(c.id) FILTER (WHERE c.seller_type = 'seller') AS seller_posts,
                       COUNT(c.id) FILTER (WHERE c.extraction_status IN ('pending', 'failed')) AS extraction_pending,
                       COUNT(c.id) FILTER (WHERE c.extraction_status = 'processing') AS extraction_processing,
                       COUNT(c.id) FILTER (WHERE c.extraction_status = 'completed') AS extraction_completed,
                       COUNT(c.id) FILTER (WHERE c.post_type = 'selling' AND c.seller_type = 'individual'
                         AND c.extraction_status = 'completed' AND jsonb_typeof(c.products) = 'array'
                         AND jsonb_array_length(c.products) > 0 AND NOT EXISTS (
                             SELECT 1 FROM post_moderation m WHERE m.post_id = p.id AND m.is_hidden = TRUE
                         )) AS client_eligible_posts,
                       COUNT(c.id) FILTER (WHERE c.post_type = 'selling' AND c.seller_type = 'individual'
                         AND c.extraction_status = 'completed'
                         AND COALESCE(jsonb_array_length(p.raw_data->'imageUrls'), 0) > 0) AS media_eligible_posts,
                       COUNT(c.id) FILTER (WHERE c.post_type = 'selling' AND c.seller_type = 'individual'
                         AND c.extraction_status = 'completed'
                         AND COALESCE(jsonb_array_length(p.raw_data->'imageUrls'), 0) > 0
                         AND (SELECT COUNT(*) FROM post_images i WHERE i.post_id = p.id)
                             >= COALESCE(jsonb_array_length(p.raw_data->'imageUrls'), 0)) AS media_completed_posts,
                       COALESCE(SUM(c.estimated_cost_usd), 0) AS classification_cost_usd,
                       COALESCE((SELECT SUM(l.estimated_cost_usd) FROM post_extraction_logs l
                         JOIN posts ep ON ep.id = l.post_id WHERE ep.crawl_run_id = r.id), 0) AS extraction_cost_usd
                FROM crawl_runs r
                LEFT JOIN posts p ON p.crawl_run_id = r.id
                LEFT JOIN post_classifications c ON c.post_id = p.id AND c.prompt_version_id = (
                    SELECT id FROM ai_prompt_versions WHERE version = 7
                )
                GROUP BY r.id
                ORDER BY r.started_at DESC, r.id DESC LIMIT :limit OFFSET :offset
            """), {"limit": limit, "offset": offset}).mappings().all()
        return {"total": total, "limit": limit, "offset": offset, "items": [dict(row) for row in rows]}
    app.include_router(router)
