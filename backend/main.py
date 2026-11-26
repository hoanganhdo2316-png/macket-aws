import os
from fastapi import FastAPI
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

load_dotenv()

app = FastAPI(title="Macket API")

db_url = URL.create(
    "postgresql+psycopg",
    username=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    host=os.getenv("DB_HOST"),
    port=int(os.getenv("DB_PORT", "5432")),
    database=os.getenv("DB_NAME"),
    query={"sslmode": "require"},
)

engine = create_engine(db_url, pool_size=2, max_overflow=1, pool_pre_ping=True)

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "macket"}

@app.get("/api/db-health")
def db_health():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}

# Admin API
from admin_routes import register_admin_routes
register_admin_routes(app, engine)


from author_routes import register_author_routes
register_author_routes(app, engine)


from settings_routes import register_settings_routes
register_settings_routes(app, engine)


from scheduler_routes import register_scheduler_routes
register_scheduler_routes(app, engine)


from collector_config_routes import register_collector_config_routes
register_collector_config_routes(app, engine)


from run_ingestion_routes import register_run_ingestion_routes
register_run_ingestion_routes(app, engine)


from apify_webhook_routes import register_apify_webhook_routes
register_apify_webhook_routes(app, engine)


from credentials_routes import register_credentials_routes
register_credentials_routes(app, engine)


from collector_credentials_routes import register_collector_credentials_routes
register_collector_credentials_routes(app, engine)


from scan_routes import register_scan_routes
register_scan_routes(app, engine)

from scan_history_routes import register_scan_history_routes
register_scan_history_routes(app, engine)


# AI System Prompt Management
from ai_prompt_routes import router as ai_prompt_router
app.include_router(ai_prompt_router)


# AI Classification Logs
from classification_logs_routes import register_classification_logs_routes
register_classification_logs_routes(app, engine)


# Public Client API
from client_routes import register_client_routes
register_client_routes(app, engine)


# Admin Product Moderation
from admin_product_routes import register_admin_product_routes
register_admin_product_routes(app, engine)
