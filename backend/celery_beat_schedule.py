"""
Celery Beat schedule configuration for periodic tasks
"""
from celery.schedules import crontab
from .config import settings

# Beat schedule for periodic tasks
beat_schedule = {
    # Daily aggregation job at 2 AM UTC
    'run-aggregation-job': {
        'task': 'backend.workers.aggregation.run_aggregation_job',
        'schedule': crontab(hour=2, minute=0),  # 2 AM UTC daily
        'options': {'queue': 'aggregation'},  # ensure Beat sends to aggregation queue
    },
    
    # Daily history cleanup at 3 AM UTC (after aggregation)
    'cleanup-history': {
        'task': 'backend.workers.history_cleanup.cleanup_history_task',
        'schedule': crontab(hour=3, minute=0),  # 3 AM UTC daily
        'options': {'queue': 'parallel'},
    },
    
    # Notification evaluation every 30 seconds
    'evaluate-notifications': {
        'task': 'backend.workers.notifications.evaluate_notifications',
        'schedule': settings.notification_check_interval,  # Every 30 seconds
        'options': {'queue': 'parallel'},
    },
    
    # Periodic device port scanning every 30 minutes
    'scan-device-ports-periodic': {
        'task': 'backend.workers.port_scanner_periodic.scan_devices_periodic',
        'schedule': crontab(minute='*/30'),  # Every 30 minutes
        'options': {'queue': 'parallel'},
    },
}

# Add Redis buffer flush task if enabled
if settings.redis_write_buffer_enabled:
    beat_schedule['flush-redis-buffers'] = {
        'task': 'backend.workers.redis_buffer.flush_buffers',
        'schedule': settings.redis_buffer_flush_interval,  # Every 5 seconds
        'options': {'queue': 'parallel'},
    }




