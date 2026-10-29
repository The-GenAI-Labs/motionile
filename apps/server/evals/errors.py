class EvalError(Exception):
    code = "eval_error"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.code)


class EvalAbortError(EvalError):
    code = "eval_aborted"


class CassetteMissError(EvalAbortError):
    code = "cassette_miss"


class EvalBudgetExceededError(EvalAbortError):
    code = "eval_budget_exceeded"


class ProviderKeysMissingError(EvalAbortError):
    code = "eval_keys_missing"


class BrowserUnavailableError(EvalError):
    code = "eval_browser_unavailable"


class DatasetError(EvalAbortError):
    code = "eval_dataset_invalid"


class ThresholdsError(EvalAbortError):
    code = "eval_thresholds_invalid"


class RecordingError(EvalAbortError):
    code = "eval_record_failed"


class OptionsError(EvalAbortError):
    code = "eval_options_invalid"


class UnknownSuiteError(OptionsError):
    code = "eval_unknown_suite"
