"""
Test task for Worker Status page - used to trigger a task for testing
"""
import logging
import time

from ..celery_app import app

logger = logging.getLogger(__name__)


@app.task(
    bind=True,
    name='backend.workers.test_task.run_test_task',
)
def run_test_task(self):
    """Celery task for testing - sleeps a few seconds and returns status.
    Triggered from Worker Status page for testing queue visibility.
    """
    task_id = self.request.id
    logger.info("Test task started: %s", task_id)
    time.sleep(5)
    logger.info("Test task completed: %s", task_id)
    return {"status": "ok", "task_id": task_id}
