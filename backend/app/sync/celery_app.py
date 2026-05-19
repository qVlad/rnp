from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "rnp",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.sync.tasks", "app.sync.tasks_abtest"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone=settings.timezone,
    enable_utc=False,
    task_acks_late=True,
    # Если worker умирает посреди задачи (SIGKILL, OOM, deploy без warm
    # shutdown) — задача возвращается в очередь и подхватывается другим
    # worker'ом. Наши sync-таски все идемпотентны (upsert по PK), поэтому
    # повторное выполнение безопасно. Без этого флага acks_late не работает
    # при ungraceful kill.
    task_reject_on_worker_lost=True,
    # Worker должен подтверждать broker'у что он жив каждые ~10 сек.
    # Long-running task (например report_detail backfill ~30 мин) без этого
    # может быть ошибочно помечен как мёртвый и таск вернётся в очередь.
    broker_heartbeat=30,
    # Redis broker visibility_timeout: сколько времени задача висит в
    # `unacked` пока worker её обрабатывает. Если worker умер до acks_late
    # → задача re-delivered другому worker'у только после истечения этого
    # таймаута. Default Celery = 3600s = 1 час (слишком долго при деплоях).
    # Ставим 600s = 10 мин: достаточно для самой долгой задачи (report_detail
    # backfill за год идёт ~50 мин, но мы делим на rrd-курсорные чанки которые
    # ack'ятся отдельно, так что одна "ack'аемая единица" не превышает 5 мин).
    broker_transport_options={
        "visibility_timeout": 600,
    },
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
        "app.sync.tasks.evaluate_notifications": {"queue": "default"},
        "app.sync.tasks.sync_chargebacks": {"queue": "default"},
        "app.sync.tasks.sync_chargebacks_for_tenant": {"queue": "default"},
        # Event-bus consumers (LEAD-004). Используют существующий
        # worker-default — добавление отдельного worker-events service
        # отложено в Этап 4 (требует ребилда docker-compose).
        "app.sync.event_consumers.consume_chargeback_telegram": {"queue": "default"},
        "app.sync.event_consumers.reclaim_all_pending": {"queue": "default"},
        "app.sync.event_consumers.smoke_publish_chargeback": {"queue": "default"},
        # A/B test tasks — rotation reads photo files from abtest_photos
        # volume mounted only on worker-default, so routing matters.
        "app.sync.tasks_abtest.rotate_running_tests": {"queue": "default"},
        "app.sync.tasks_abtest.rotation_check_one_test": {"queue": "default"},
        "app.sync.tasks_abtest.poll_abtest_budgets": {"queue": "advert"},
        "app.sync.tasks_abtest.poll_abtest_budgets_for_tenant": {"queue": "advert"},
        "app.sync.tasks_abtest.sync_abtest_stats_full": {"queue": "advert"},
        "app.sync.tasks_abtest.sync_abtest_stats_for_tenant": {"queue": "advert"},
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
        # Документы: уведомления о выкупе + акты взаимозачёта (Documents API).
        # 07:00 MSK после report_detail (04:15) и paid_storage (05:30) — даём
        # WB время сгенерировать новые документы. Rate limit 1/10sec на download,
        # 13 документов за 90 дней = ~2 минуты на синк, не нагружает API.
        "sync-redeem-notifications-daily": {
            "task": "app.sync.tasks.sync_redeem_notifications",
            "schedule": crontab(hour=7, minute=0),
        },
        "sync-offset-acts-daily": {
            "task": "app.sync.tasks.sync_offset_acts",
            "schedule": crontab(hour=7, minute=15),
        },
        # Чарджбэки/штрафы: сканируем wb_report_detail после report_detail-sync
        # за последние 60 дней. Без новых WB-вызовов — чистый SQL UPSERT, дешёво.
        "sync-chargebacks-daily": {
            "task": "app.sync.tasks.sync_chargebacks",
            "schedule": crontab(hour=4, minute=45),
        },
        # Event-bus consumer (LEAD-004) — tick каждые 30 сек, read with
        # 5-second block. Если событий нет — задача быстро завершится.
        "consume-chargeback-telegram-30s": {
            "task": "app.sync.event_consumers.consume_chargeback_telegram",
            "schedule": 30.0,
        },
        # DLQ watchdog — раз в 5 мин проверяет pending list и перевыдаёт
        # застрявшие сообщения (idle > 10 мин). После 5 retries → DLQ.
        "event-bus-reclaim-5min": {
            "task": "app.sync.event_consumers.reclaim_all_pending",
            "schedule": 300.0,
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
        # WB Jam — поисковые запросы по карточкам (платная подписка).
        # Раз в сутки достаточно: запросы и их статистика обновляются с
        # задержкой 1-2 дня. Расход на analytics: ~30 SKU × 1 запрос ≈ 10 мин
        # с 20-секундным минимальным интервалом — укладываемся в окно.
        "sync-jam-daily": {
            "task": "app.sync.tasks.sync_jam",
            "schedule": crontab(hour=5, minute=30),
        },
        # Telegram daily digest — 09:00 MSK (no-op if bot is not configured)
        "tg-daily-digest": {
            "task": "app.sync.tasks.send_daily_digest",
            "schedule": crontab(hour=9, minute=0),
        },
        # Notification rules — каждый час, оценка active rules + send to TG
        "notifications-hourly": {
            "task": "app.sync.tasks.evaluate_notifications",
            "schedule": crontab(minute=10),
        },
        # --- A/B testing ---
        # Rotation проверка каждые 15 мин — sufficient гранулярность даже
        # для TIME-триггера 30 мин (max джиттер 15 мин, что приемлемо).
        # При активных тестах с быстрым TIME-триггером (<15 мин) — точечная
        # самоплан через rotation_check_one_test с countdown.
        "abtest-rotate-running": {
            "task": "app.sync.tasks_abtest.rotate_running_tests",
            "schedule": crontab(minute="*/15"),
        },
        # Budget polling — лёгкий GET /adv/v1/budget per running test с
        # autoTopup. 30 мин гранулярности достаточно — при пополнении 1000₽
        # реклама обычно идёт 1-3 часа.
        "abtest-poll-budgets": {
            "task": "app.sync.tasks_abtest.poll_abtest_budgets",
            "schedule": crontab(minute="5,35"),
        },
        # Full stats sync — 4x/day. Adv API ограничения строгие (3/min,
        # min_interval 20s) — поэтому редко. Промежуточные snapshots
        # делает сама rotation через `_check_and_rotate_one` → `sync_test_stats`.
        # Это покрывает «снять снапшот при каждой ротации» — full sync здесь
        # для тестов без частых ротаций (например long TIME-триггер) и для
        # nm-report (более частый чем daily, что бы новые impressions попадали
        # в abtest_daily_stat без ожидания ротации).
        "abtest-sync-stats-full": {
            "task": "app.sync.tasks_abtest.sync_abtest_stats_full",
            "schedule": crontab(hour="1,7,13,19", minute=50),
        },
    },
)
