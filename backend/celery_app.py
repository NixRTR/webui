"""
Celery application instance for background workers
"""
from celery import Celery
from .celery_config import *

# Create Celery app instance
app = Celery('router_webui')

# Load configuration from celery_config module
app.config_from_object('backend.celery_config')

# Auto-discover tasks from workers module
app.autodiscover_tasks(['backend.workers'])

