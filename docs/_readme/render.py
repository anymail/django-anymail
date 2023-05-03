#!/usr/bin/env python
# Render a README file (roughly) as it would appear on PyPI

import argparse
import sys
from importlib.metadata import PackageNotFoundError, metadata
from pathlib import Path
from typing import Dict, Optional

import readme_renderer.rst
from docutils.core import publish_string
from docutils.utils import SystemMessage

# Docutils template.txt in our directory:
DEFAULT_TEMPLATE_FILE = Path(__file__).with_name("template.txt").absolute()


def get_package_readme(package: str) -> str:
    # Note: "description" was added to metadata in Python 3.10
    return metadata(package)["description"]


class ReadMeHTMLWriter(readme_renderer.rst.Writer):
    translator_class = readme_renderer.rst.ReadMeHTMLTranslator

    def interpolation_dict(self) -> Dict[str, str]:
        result = super().interpolation_dict()
        # clean the same parts as readme_renderer.rst.render:
        clean = readme_renderer.rst.clean
        result["docinfo"] = clean(result["docinfo"])
        result["body"] = result["fragment"] = clean(result["fragment"])
        return result


def render(source_text: str, warning_stream=sys.stderr) -> Optional[str]:
    # Adapted from readme_renderer.rst.render
    settings = readme_renderer.rst.SETTINGS.copy()
    settings.update(
        {
            "warning_stream": warning_stream,
            "template": DEFAULT_TEMPLATE_FILE,
            # Input and output are text str (we handle decoding/encoding):
            "input_encoding": "unicode",
            "output_encoding": "unicode",
            # Exit with error on docutils warning or above.
            # (There's discussion of having readme_renderer ignore warnings;
            # this ensures they'll be treated as errors here.)
            "halt_level": 2,  # (docutils.utils.Reporter.WARNING_LEVEL)
            # Report all docutils warnings or above.
            # (The readme_renderer default suppresses this output.)
            "report_level": 2,  # (docutils.utils.Reporter.WARNING_LEVEL)
        }
    )

    writer = ReadMeHTMLWriter()

    try:
        return publish_string(
            source_text,
            writer=writer,
            settings_overrides=settings,
        )
    except SystemMessage:
        warning_stream.write("Error rendering readme source.\n")
        return None


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Render readme file as it would appear on PyPI"
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "-p", "--package", help="Source readme from package's metadata"
    )
    input_group.add_argument(
        "-i",
        "--input",
        help="Source readme.rst file ('-' for stdin)",
        type=argparse.FileType("r"),
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Output file (default: stdout)",
        type=argparse.FileType("w"),
        default="-",
    )

    args = parser.parse_args(argv)
    if args.package:
        try:
            source_text = get_package_readme(args.package)
        except PackageNotFoundError:
            print(f"Package not installed: {args.package!r}", file=sys.stderr)
            sys.exit(2)
        if source_text is None:
            print(f"No metadata readme for {args.package!r}", file=sys.stderr)
            sys.exit(2)
    else:
        source_text = args.input.read()
    rendered = render(source_text)
    if rendered is None:
        sys.exit(2)
    args.output.write(rendered)


if __name__ == "__main__":
    main()
