from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "rnp",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.sync.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone=settings.timezone,
    enable_utc=False,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_queue="default",
    task_routes={
        "app.sync.tasks.sync_orders": {"queue": "stats"},
        "app.sync.tasks.sync_sales": {"queue": "stats"},
        "app.sync.tasks.sync_stocks": {"queue": "stats"},
        "app.sync.tasks.sync_report_detail": {"queue": "stats"},
        "app.sync.tasks.sync_report_detail_backfill": {"queue": "stats"},
        "app.sync.tasks.sync_report_detail_for_tenant": {"queue": "stats"},
        "app.sync.tasks.sync_ad_campaigns": {"queue": "advert"},
        "app.sync.tasks.sync_ad_campaign_details": {"queue": "advert"},
        "app.sync.tasks.sync_ad_stats": {"queue": "advert"},
        "app.sync.tasks.send_daily_digest": {"queue": "default"},
    },
    # Beat schedule design constraints:
    #   - WB Statistics: docs say 1 req/min sustained, but the *real* burst
    #     window observed in production is 5-10 min: a successful big response
    #     is followed by a 429 on the very next call ~5 min later. So we
    #     space stats tasks 15 min apart — gives WB time to forget the burst.
    #   - stocks is a full snapshot every call; 2x/day is enough.
    #   - report_detail: once daily at 04:15 MSK (covers yesterday's closed rows).
    #   - Advert: /adv/v3/fullstats limit is 3 req/min, ~20s between calls.
    #     fetch_fullstats internally chunks (50 IDs/call) and the in-process
    #     rate_limiter (configured 3/min) handles spacing. Beat fires ad_stats
    #     once per hour.
    beat_schedule={
        # Statistics queue — calibrated for **Base token** limits (acc=3):
        #   /orders          ≤ 1 / 3 hours → schedule every 3 hours
        #   /sales           ≤ 1 / 2 hours → schedule every 2 hours
        #   /stocks          ≤ 1 / 3 hours → 2x/day is plenty (full snapshot)
        #   /reportDetail    ≤ 2 / 24 hours → 1x/day (next-best granularity)
        # If token type changes to Personal (acc=1), can be much denser
        # (every 30 min for orders/sales is safe).
        # See WB_API_REFERENCE.md §3.
        "sync-orders": {
            "task": "app.sync.tasks.sync_orders",
            "schedule": crontab(hour="0,3,6,9,12,15,18,21", minute=10),
        },
        "sync-sales": {
            "task": "app.sync.tasks.sync_sales",
            "schedule": crontab(hour="0,2,4,6,8,10,12,14,16,18,20,22", minute=40),
        },
        # stocks: 2x/day (at 06:30 MSK and 18:30 MSK) — full snapshot is fine
        "sync-stocks": {
            "task": "app.sync.tasks.sync_stocks",
            "schedule": crontab(hour="6,18", minute=30),
        },
        # report_detail: once daily at 04:15 MSK (covers yesterday's closed rows)
        "sync-report-detail-daily": {
            "task": "app.sync.tasks.sync_report_detail",
            "schedule": crontab(hour=4, minute=15),
        },
        # Weekly safety net for the reconciliation page: the daily task only
        # refreshes recent rows, while this keeps the 12-week history populated
        # without upserting ~90 days of report_detail every single day.
        "sync-report-detail-backfill-weekly": {
            "task": "app.sync.tasks.sync_report_detail_backfill",
            "schedule": crontab(hour=6, minute=15, day_of_week="sun"),
        },
        # paid_storage: once daily at 05:30 MSK — async-task на seller-analytics-api,
        # отдельная категория `analytics` (3/мин). Тянем за последние 7 дней.
        "sync-paid-storage-daily": {
            "task": "app.sync.tasks.sync_paid_storage",
            "schedule": crontab(hour=5, minute=30),
        },
        # Advert queue — production observation: WB penalises >=2 advert calls
        # within ~60 min with 50-60 min cooldown. Schedule must keep ≥1h gap
        # between any two advert-category calls, idealy >=2h.
        # Each task makes exactly ONE WB call.
        # Layout (Moscow time):
        #   00:15, 06:15, 12:15, 18:15  — ad_stats     (every 6 hours = 4x/day)
        #   03:30                       — ad_campaigns (daily; refreshes IDs)
        #   04:45                       — ad_campaign_details (daily; fills NULL)
        # Gaps: ad_stats 00:15 → ad_campaigns 03:30 = 3h15m
        #       ad_campaigns 03:30 → ad_campaign_details 04:45 = 1h15m
        #       ad_campaign_details 04:45 → ad_stats 06:15 = 1h30m
        "sync-ad-stats": {
            "task": "app.sync.tasks.sync_ad_stats",
            "schedule": crontab(hour="0,6,12,18", minute=15),
        },
        "sync-ad-campaigns-daily": {
            "task": "app.sync.tasks.sync_ad_campaigns",
            "schedule": crontab(hour=3, minute=30),
        },
        "sync-ad-campaign-details-daily": {
            "task": "app.sync.tasks.sync_ad_campaign_details",
            "schedule": crontab(hour=4, minute=45),
        },
        # Photo URLs from WB Content API — раз в сутки достаточно, фото
        # карточек редко меняется. Заполняет products.photo_url чтобы
        # photo-proxy не перебирал basket-CDN'ы.
        "sync-product-photos-daily": {
            "task": "app.sync.tasks.sync_product_photos",
            "schedule": crontab(hour=5, minute=0),
        },
        # Telegram daily digest — 09:00 MSK (no-op if bot is not configured)
        "tg-daily-digest": {
            "task": "app.sync.tasks.send_daily_digest",
            "schedule": crontab(hour=9, minute=0),
        },
    },
)
