from motionile.core.config import get_settings
from motionile.core.logging import configure_logging
from motionile.core.tasks.app import create_task_app

settings = get_settings()
configure_logging(settings)
app = create_task_app(settings)
