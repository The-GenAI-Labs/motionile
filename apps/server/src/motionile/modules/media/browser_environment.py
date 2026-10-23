from motionile.core.config import Settings


def browser_environment(settings: Settings) -> dict[str, str]:
    process = settings.process_environment
    work_directory = settings.render.work_directory
    home = process.home or (str(work_directory) if work_directory is not None else "")
    allowed = {
        "PATH": process.path,
        "HOME": home,
        "SYSTEMROOT": process.system_root,
        "TEMP": process.temp,
        "TMP": process.tmp,
        "TMPDIR": process.tmpdir,
    }
    return {name: value for name, value in allowed.items() if value}
