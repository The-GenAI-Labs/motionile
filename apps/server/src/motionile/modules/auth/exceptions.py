from fastapi import Request
from fastapi.responses import JSONResponse

from motionile.core.errors import ForbiddenError, ProblemDetails, problem_response, request_id_of
from motionile.core.security.cookies import CookieManager
from motionile.modules.auth.schemas import ChallengeResponse


class VerificationProblem(ProblemDetails):
    challenge: ChallengeResponse


class VerificationRequiredError(ForbiddenError):
    default_code = "verification_required"
    title = "Contact verification required"

    def __init__(self, ticket: str, challenge: ChallengeResponse) -> None:
        super().__init__()
        self.ticket = ticket
        self.challenge = challenge


async def verification_required_response(request: Request, error: Exception) -> JSONResponse:
    if not isinstance(error, VerificationRequiredError):
        raise TypeError("Expected a verification-required error")
    response = problem_response(
        VerificationProblem(
            status=403,
            code=error.code,
            title=error.title,
            instance=request.url.path,
            request_id=request_id_of(request),
            challenge=error.challenge,
        )
    )
    CookieManager(request.app.state.resources.settings.auth.cookie_domain).set_ticket(response, error.ticket)
    return response
