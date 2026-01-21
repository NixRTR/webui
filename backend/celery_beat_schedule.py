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
    },
    
    # Notification evaluation every 30 seconds
    'evaluate-notifications': {
        'task': 'backend.workers.notifications.evaluate_notifications',
        'schedule': settings.notification_check_interval,  # Every 30 seconds
    },
}

# Add Redis buffer flush task if enabled
if settings.redis_write_buffer_enabled:
    beat_schedule['flush-redis-buffers'] = {
        'task': 'backend.workers.redis_buffer.flush_buffers',
        'schedule': settings.redis_buffer_flush_interval,  # Every 5 seconds
    }




