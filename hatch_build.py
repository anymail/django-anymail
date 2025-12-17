# Hatch custom build hook that generates dynamic readme.

import re
from pathlib import Path

from hatchling.metadata.plugin.interface import MetadataHookInterface


def freeze_readme_versions(text: str, version: str) -> str:
    """
    Rewrite links in readme text to refer to specific version.
    (This assumes version X.Y will be tagged "vX.Y" in git.)
    """
    release_tag = f"v{version}"
    # (?<=...) is "positive lookbehind": must be there, but won't get replaced
    text = re.sub(
        # GitHub Actions badge: badge.svg?branch=main --> badge.svg?tag=vX.Y.Z:
        r"(?<=badge\.svg\?)branch=main",
        f"tag={release_tag}",
        text,
    )
    return re.sub(
        # GitHub Actions status links: branch:main --> branch:vX.Y.Z:
        r"(?<=branch:)main"
        # ReadTheDocs links: /stable --> /vX.Y.Z:
        r"|(?<=/)stable"
        # ReadTheDocs badge: version=stable --> version=vX.Y.Z:
        r"|(?<=version=)stable",
        release_tag,
        text,
    )


def strip_section(text: str, start: str, end: str) -> str:
    """Remove lines between start and end, inclusive."""
    lines = text.splitlines(keepends=True)
    result = []
    skip = False

    for line in lines:
        if line.strip() == start:
            skip = True
            continue
        if line.strip() == end:
            skip = False
            continue
        if not skip:
            result.append(line)

    return "".join(result)


class CustomMetadataHook(MetadataHookInterface):
    def update(self, metadata):
        """
        Update the project table's metadata.
        """
        readme_path = Path(self.root) / self.config["readme"]
        content_type = self.config.get("content-type", "text/x-rst")
        version = metadata["version"]

        readme_text = readme_path.read_text()
        # Remove sponsor-logos (uses raw html directive that doesn't work
        # on PyPI, plus we don't really want to bake logos into releases).
        readme_text = strip_section(
            readme_text, ".. BEGIN sponsor-logos", ".. END sponsor-logos"
        )
        readme_text = freeze_readme_versions(readme_text, version)

        metadata["readme"] = {
            "content-type": content_type,
            "text": readme_text,
        }
