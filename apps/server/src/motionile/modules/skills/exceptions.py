from http import HTTPStatus

from motionile.core.errors import AppError, NotFoundError


class SkillNotFoundError(NotFoundError):
    default_code = "skill_not_found"
    title = "Skill not found"


class SkillEmbeddingUnavailableError(AppError):
    status_code = HTTPStatus.BAD_GATEWAY
    default_code = "skill_embedding_unavailable"
    title = "The embedding provider is unavailable"


class SkillLibraryInvalidError(AppError):
    status_code = HTTPStatus.INTERNAL_SERVER_ERROR
    default_code = "skill_library_invalid"
    title = "The shipped skill library is invalid"


class SkillEmbeddingDimensionsError(AppError):
    status_code = HTTPStatus.INTERNAL_SERVER_ERROR
    default_code = "skill_embedding_dimensions"
    title = "The embedder does not match the embedding column"
