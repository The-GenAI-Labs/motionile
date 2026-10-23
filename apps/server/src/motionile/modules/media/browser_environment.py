from motionile.core.config import Settings


def browser_environment(settings: Settings) -> dict[str, str]:
    process = settings.process_environment
    home = str(settings.render.work_directory) if settings.render.work_directory is not None else process.home
    allowed = {
        "PATH": process.path,
        "HOME": home,
        "SYSTEMROOT": process.system_root,
        "TEMP": process.temp,
        "TMP": process.tmp,
        "TMPDIR": process.tmpdir,
    }
    return {name: value for name, value in allowed.items() if value}
