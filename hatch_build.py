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
    return re.sub(
        # (?<=...) is "positive lookbehind": must be there, but won't get replaced
        # GitHub Actions build status: branch=main --> branch=vX.Y.Z:
        r"(?<=branch[=:])main"
        # ReadTheDocs links: /stable --> /vX.Y.Z:
        r"|(?<=/)stable"
        # ReadTheDocs badge: version=stable --> version=vX.Y.Z:
        r"|(?<=version=)stable",
        release_tag,
        text,
    )


class CustomMetadataHook(MetadataHookInterface):
    def update(self, metadata):
        """
        Update the project table's metadata.
        """
        readme_path = Path(self.root) / self.config["readme"]
        content_type = self.config.get("content-type", "text/x-rst")
        version = metadata["version"]

        readme_text = readme_path.read_text()
        readme_text = freeze_readme_versions(readme_text, version)

        metadata["readme"] = {
            "content-type": content_type,
            "text": readme_text,
        }
