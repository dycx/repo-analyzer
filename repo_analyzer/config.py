"""Configuration dataclass for the analysis pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    """All pipeline parameters in a single typed object."""

    repo_path: Path = field(default_factory=lambda: Path("."))
    output: Path | None = None
    phase_start: int = 0
    phase_end: int = 4
    base_url: str = "http://127.0.0.1:1234/v1"
    api_key: str | None = None
    model: str = "qwen3.5-35b-a3b"
    max_files: int = 5000
    timeout: float = 300.0
    max_retries: int = 3
    context_size: int = 4000
    skip_tests: bool = False
    skip_synthesis: bool = False
    force: bool = False
    verbose: bool = False

    @property
    def repo_name(self) -> str:
        return self.repo_path.name

    @property
    def analysis_dir(self) -> Path:
        return self.repo_path / ".code-analysis"

    def phase_in_range(self, phase: int) -> bool:
        return self.phase_start <= phase <= self.phase_end
