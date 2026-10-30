import motionile.models  # noqa: F401 # type: ignore[reportUnusedImport]
from motionile.core.config import get_settings
from motionile.core.logging import configure_logging
from motionile.core.resources import Resources
from motionile.core.tasks.app import create_task_app
from motionile.modules.generation import LazyPipelineRunner, install_runner
from motionile.modules.prompts import EvalExecutor, install_eval_executor

settings = get_settings()
configure_logging(settings)
app = create_task_app(settings)
install_runner(LazyPipelineRunner(settings))


def eval_executor_factory(resources: Resources) -> EvalExecutor:
    from evals.executor import build_eval_executor  # noqa: PLC0415

    return build_eval_executor(resources)


install_eval_executor(eval_executor_factory)
