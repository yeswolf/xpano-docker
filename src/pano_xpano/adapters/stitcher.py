from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from PIL import Image

from pano_xpano.application.ports import StitcherError, StitchOutput

logger = logging.getLogger(__name__)


class XpanoStitcher:
    def __init__(self, binary: str) -> None:
        self._binary = binary

    def stitch(
        self,
        paths: list[Path],
        output: Path,
        timeout_s: int,
        use_xvfb: bool,
    ) -> StitchOutput:
        if not paths:
            raise StitcherError("no input images")
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists():
            output.unlink()
        command = [
            self._binary,
            *[str(path) for path in paths],
            f"--output={output}",
        ]
        result = self._run(command, output, timeout_s, use_xvfb)
        if result.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
            message = (result.stderr or result.stdout or "Xpano produced no output").strip()
            raise StitcherError(message[-2000:])
        width, height = _image_size(output)
        return StitchOutput(path=output, width=width, height=height)

    def _run(
        self,
        command: list[str],
        output: Path,
        timeout_s: int,
        use_xvfb: bool,
    ) -> subprocess.CompletedProcess[str]:
        if use_xvfb and shutil.which("xvfb-run"):
            command = ["xvfb-run", "-a", *command]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
        except FileNotFoundError as error:
            raise StitcherError(f"Xpano binary not found: {self._binary}") from error
        except subprocess.TimeoutExpired as error:
            raise StitcherError(f"Xpano timed out after {timeout_s}s") from error
        if (
            completed.returncode != 0
            and not use_xvfb
            and shutil.which("xvfb-run")
            and _looks_like_display_error(completed.stderr + completed.stdout)
        ):
            logger.info("Xpano needs a display, retrying with xvfb-run")
            try:
                return subprocess.run(
                    ["xvfb-run", "-a", *command],
                    capture_output=True,
                    text=True,
                    timeout=timeout_s,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                raise StitcherError(f"Xpano failed under xvfb: {error}") from error
        return completed


def _looks_like_display_error(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in ("display", "x11", "xcb", "sdl", "wayland", "egl")
    )


def _image_size(path: Path) -> tuple[int, int]:
    try:
        with Image.open(path) as image:
            return image.width, image.height
    except (OSError, ValueError):
        return 0, 0
