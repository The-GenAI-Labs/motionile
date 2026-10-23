from pathlib import Path

from motionile.engine.ffmpeg import FfmpegTools, run_ffmpeg


class MediaFactory:
    def __init__(self, tools: FfmpegTools, directory: Path) -> None:
        self.tools = tools
        self.directory = directory

    async def make(self, name: str, source: str, *output_arguments: str) -> Path:
        path = self.directory / name
        await run_ffmpeg(
            self.tools,
            ["-f", "lavfi", "-i", source, *output_arguments, "-y", str(path)],
            timeout_seconds=120,
        )
        return path
