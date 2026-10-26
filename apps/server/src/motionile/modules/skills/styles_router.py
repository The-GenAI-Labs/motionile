from fastapi import APIRouter, Depends, Response, status

from motionile.core.dependencies import ResourcesDep
from motionile.core.errors import problem_responses
from motionile.core.ratelimit.limiter import rate_limit
from motionile.modules.auth import CurrentPrincipalDep
from motionile.modules.skills.factory import build_skill_catalog
from motionile.modules.skills.schemas import StyleListView, StyleView

styles_router = APIRouter(
    prefix="/styles",
    tags=["styles"],
    dependencies=[Depends(rate_limit("api.default"))],
    responses=problem_responses(401),
)


@styles_router.get(
    "",
    response_model=StyleListView,
    status_code=status.HTTP_200_OK,
    summary="List the video styles with their palette swatches",
)
async def list_styles(_: CurrentPrincipalDep, resources: ResourcesDep, response: Response) -> StyleListView:
    options = await build_skill_catalog(resources).styles()
    response.headers["Cache-Control"] = "private, max-age=300"
    return StyleListView(
        items=[
            StyleView(
                slug=option.slug,
                name=option.name,
                description=option.description,
                background=option.palette["--mo-bg"],
                surface=option.palette["--mo-surface"],
                text=option.palette["--mo-text"],
                accent=option.palette["--mo-accent"],
            )
            for option in options
        ]
    )
