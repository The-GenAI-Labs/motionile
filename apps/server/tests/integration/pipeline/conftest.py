from collections.abc import AsyncIterator

import pytest
from tests.fakes.generation import FakeEditGuard, RecordingDispatch
from tests.integration.engine.render.support import resolve_tools
from tests.integration.generation_support import GenerationApi, build_generation_service, purge_generation_data
from tests.integration.media_support import MediaApi
from tests.integration.pipeline.support import PipelineEnv, install_voice, purge_pipeline_data, seed_catalogs

from motionile.core.config import AppEnv, AppSettings, ProvidersMode, RenderSettings, Settings
from motionile.engine.ffmpeg import FfmpegTools
from motionile.modules.generation import pipeline_deps
from motionile.modules.generation.dependencies import get_generation_service
from motionile.modules.media import render_pipeline_for
from motionile.modules.media.pipeline.toolchain import build_toolchain

FPS = 24
TAIL_MS = 600


@pytest.fixture
def settings(settings: Settings, tmp_path_factory: pytest.TempPathFactory) -> Settings:
    work = tmp_path_factory.mktemp("pipeline-work")
    return settings.model_copy(
        update={
            "app": AppSettings(env=AppEnv.CI, providers_mode=ProvidersMode.FAKE),
            "render": RenderSettings(
                work_directory=work,
                x264_preset="veryfast",
                parallel_pages=3,
                chunk_seconds=2,
                tail_ms=TAIL_MS,
                scene_padding_ms=300,
                page_load_timeout_seconds=30,
                ready_timeout_seconds=30,
                frame_timeout_seconds=20,
                min_free_disk_mb=1,
            ),
        }
    )


@pytest.fixture(scope="session")
def tools() -> FfmpegTools:
    found = resolve_tools()
    if found is None:
        pytest.skip("ffmpeg and ffprobe are not available; set RENDER_FFMPEG_PATH and RENDER_FFPROBE_PATH")
    return found


@pytest.fixture
async def pipeline_env(
    media_api: MediaApi, settings: Settings, tools: FfmpegTools, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[PipelineEnv]:
    del tools
    resources = media_api.resources
    voice_id = await install_voice(media_api.database)
    await seed_catalogs(resources)
    dispatch, guard = RecordingDispatch(), FakeEditGuard()
    service = build_generation_service(media_api, dispatch, guard)
    media_api.app.dependency_overrides[get_generation_service] = lambda: service
    generation = GenerationApi(media_api, service, dispatch, guard, voice_id)
    pipeline = render_pipeline_for(resources, lambda fps: build_toolchain(settings, fps))
    env = PipelineEnv(generation, settings, pipeline)
    monkeypatch.setattr(pipeline_deps, "llm_client_for", env.scripted_llm)
    yield env
    media_api.app.dependency_overrides.pop(get_generation_service, None)
    await purge_pipeline_data(generation)
    await purge_generation_data(media_api.database)
