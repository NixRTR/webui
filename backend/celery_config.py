"""
Celery configuration for background workers
"""
from .config import settings
from .celery_beat_schedule import beat_schedule as beat_schedule_config

# Task serialization
task_serializer = 'json'
accept_content = ['json']
result_serializer = 'json'

# Timezone
timezone = 'UTC'
enable_utc = True

# Task execution
task_always_eager = False  # Don't execute tasks synchronously
task_eager_propagates = True

# Task time limits (in seconds)
task_time_limit = 3600  # 1 hour hard limit
task_soft_time_limit = 3300  # 55 minutes soft limit

# Worker settings
worker_prefetch_multiplier = 4
worker_max_tasks_per_child = 1000  # Restart worker after N tasks to prevent memory leaks
worker_disable_rate_limits = False

# Modules to import so workers register all tasks (autodiscover looks for .tasks submodule we don't use)
include = [
    "backend.workers.aggregation",
    "backend.workers.notifications",
    "backend.workers.redis_buffer",
    "backend.workers.history_cleanup",
    "backend.workers.port_scanner",
    "backend.workers.port_scanner_periodic",
    "backend.workers.test_task",
]

# Task routing: sequential (one at a time) vs parallel (concurrent)
task_routes = {
    # Sequential: one at a time (concurrency=1 worker)
    'backend.workers.port_scanner.scan_new_device_ports': {'queue': 'sequential'},
    # Parallel: can run concurrently
    'backend.workers.aggregation.run_aggregation_job': {'queue': 'parallel'},
    'backend.workers.notifications.evaluate_notifications': {'queue': 'parallel'},
    'backend.workers.redis_buffer.flush_buffers': {'queue': 'parallel'},
    'backend.workers.port_scanner_periodic.scan_devices_periodic': {'queue': 'parallel'},
    'backend.workers.history_cleanup.cleanup_history_task': {'queue': 'parallel'},
    'backend.workers.port_scanner.scan_device_ports_task': {'queue': 'parallel'},
    'backend.workers.test_task.run_test_task': {'queue': 'parallel'},
}

# Task retry settings
task_acks_late = True
task_reject_on_worker_lost = True

# Broker connection settings
broker_connection_retry_on_startup = True
broker_connection_retry = True
broker_connection_max_retries = 10

# Redis broker URL
broker_url = f"redis://{settings.redis_host}:{settings.redis_port}/{settings.redis_db}"
if settings.redis_password:
    broker_url = f"redis://:{settings.redis_password}@{settings.redis_host}:{settings.redis_port}/{settings.redis_db}"

# Result backend URL (same as broker)
result_backend = broker_url

# Celery Beat schedule
beat_schedule = beat_schedule_config

