from motionile.core.errors import problem_responses

LIST_ERRORS = problem_responses(401, 403, 422)
DETAIL_ERRORS = problem_responses(401, 403, 404, 422)
WRITE_ERRORS = problem_responses(401, 403, 404, 409, 422)
PROVIDER_ERRORS = problem_responses(401, 403, 404, 409, 422, 502, 503)
