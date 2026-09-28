"""Versioned prompt files: ``prompts/extract_<version>.md`` (``# System`` + ``# User``)."""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

PROMPTS_DIR = Path("prompts")
_PLACEHOLDERS = ("{company_name}", "{document}", "{truncation_note}")


@dataclass(frozen=True)
class Prompt:
    version: str
    system: str
    user_template: str
    sha256: str  # of the whole file; guards against editing a prompt without bumping its version

    def render_user(self, *, company_name: str, document: str, truncated: bool) -> str:
        note = (
            "\n(The document was truncated to fit the length budget; later sections are missing.)"
            if truncated
            else ""
        )
        # Plain replacement, not str.format: documents contain braces.
        return (
            self.user_template.replace("{company_name}", company_name)
            .replace("{truncation_note}", note)
            .replace("{document}", document)
        )


def load_prompt(version: str, prompts_dir: Path = PROMPTS_DIR) -> Prompt:
    """Load ``extract_<version>.md``; raise if it is missing or malformed."""
    if not re.fullmatch(r"v\d+[a-z0-9_]*", version):
        raise ValueError(f"prompt version must look like 'v1', got {version!r}")
    path = prompts_dir / f"extract_{version}.md"
    if not path.exists():
        raise FileNotFoundError(f"no prompt file at {path}")
    raw = path.read_text(encoding="utf-8")
    match = re.fullmatch(r"\s*# System\s*\n(.*?)\n# User\s*\n(.*)", raw, re.DOTALL)
    if match is None:
        raise ValueError(f"{path} must contain '# System' then '# User' sections")
    system, user = match.group(1).strip(), match.group(2).strip()
    missing = [p for p in _PLACEHOLDERS if p not in user]
    if missing:
        raise ValueError(f"{path} user section is missing placeholders {missing}")
    return Prompt(
        version=version,
        system=system,
        user_template=user,
        sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    )
