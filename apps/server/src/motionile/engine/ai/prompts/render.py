from collections.abc import Mapping

from jinja2 import StrictUndefined, TemplateError, TemplateSyntaxError, meta
from jinja2.sandbox import SandboxedEnvironment

from motionile.engine.ai.ports import ActivePrompt

CANARY_VARIABLE = "canary"

ENVIRONMENT = SandboxedEnvironment(
    undefined=StrictUndefined,
    autoescape=False,
    keep_trailing_newline=True,
)


class PromptRenderError(Exception):
    pass


def referenced_variables(body: str) -> frozenset[str]:
    try:
        return frozenset(meta.find_undeclared_variables(ENVIRONMENT.parse(body)))
    except TemplateSyntaxError as error:
        raise PromptRenderError(f"the prompt template is invalid at line {error.lineno}: {error.message}") from error


def render_prompt(body: str, variables: Mapping[str, str], canary: str) -> str:
    if CANARY_VARIABLE in variables:
        raise PromptRenderError("the canary is supplied separately and cannot be a variable")
    referenced = referenced_variables(body)
    unknown = sorted(set(variables) - referenced)
    if unknown:
        raise PromptRenderError(f"unknown variables: {', '.join(unknown)}")
    missing = sorted(referenced - set(variables) - {CANARY_VARIABLE})
    if missing:
        raise PromptRenderError(f"missing variables: {', '.join(missing)}")
    try:
        return ENVIRONMENT.from_string(body).render({**variables, CANARY_VARIABLE: canary})
    except TemplateError as error:
        raise PromptRenderError(f"the prompt could not be rendered: {error.message}") from error
    except TypeError as error:
        raise PromptRenderError(
            "the prompt could not be rendered: it refers to a template that cannot be loaded"
        ) from error


def render_active(prompt: ActivePrompt, variables: Mapping[str, str] | None = None) -> str:
    return render_prompt(prompt.body, variables or {}, prompt.canary)
