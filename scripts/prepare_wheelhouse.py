"""Prepare installed production dependencies as wheels for a fully offline smoke test."""

import base64
import csv
import hashlib
import io
import zipfile
from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement
from packaging.tags import parse_tag, sys_tags
from packaging.utils import canonicalize_name


def _dependencies(project: str) -> dict[str, metadata.Distribution]:
    selected = {}
    processed = set()
    pending = [(Requirement(project), set())]
    while pending:
        requirement, parent_extras = pending.pop()
        if requirement.marker and not any(
            requirement.marker.evaluate({"extra": extra})
            for extra in parent_extras or {""}
        ):
            continue
        name = canonicalize_name(requirement.name)
        key = (name, frozenset(requirement.extras))
        if key in processed:
            continue
        processed.add(key)
        distribution = metadata.distribution(name)
        if name != canonicalize_name(project):
            selected[name] = distribution
        for dependency in distribution.requires or []:
            pending.append((Requirement(dependency), requirement.extras))
    return selected


def prepare_wheelhouse(project: str, directory: Path) -> None:
    """Repack only validated installed runtime dependencies, regenerating RECORD.

    This uses the project's declared transitive runtime requirements, not arbitrary
    development packages or the editable project. It avoids registry/cache metadata
    during installation and retains platform tags and original package metadata.
    """
    directory.mkdir()
    supported = set(sys_tags())
    for name, distribution in _dependencies(project).items():
        wheel_metadata = distribution.read_text("WHEEL") or ""
        tags = [
            line.removeprefix("Tag: ")
            for line in wheel_metadata.splitlines()
            if line.startswith("Tag: ")
        ]
        tag = next(tag for tag in tags if parse_tag(tag) & supported)
        filename = f"{name.replace('-', '_')}-{distribution.version}-{tag}.whl"
        rows = []
        record_name = None
        with zipfile.ZipFile(
            directory / filename, "w", zipfile.ZIP_DEFLATED
        ) as archive:
            for relative in distribution.files or []:
                if ".." in relative.parts or "__pycache__" in relative.parts:
                    continue
                if relative.name == "RECORD":
                    record_name = str(relative)
                    continue
                if relative.name in {
                    "INSTALLER",
                    "REQUESTED",
                    "direct_url.json",
                    "RECORD.jws",
                    "RECORD.p7s",
                }:
                    continue
                source = Path(distribution.locate_file(relative))
                if not source.is_file():
                    continue
                data = source.read_bytes()
                archive.writestr(str(relative), data)
                digest = (
                    base64.urlsafe_b64encode(hashlib.sha256(data).digest())
                    .rstrip(b"=")
                    .decode()
                )
                rows.append((str(relative), f"sha256={digest}", str(len(data))))
            if record_name is None:
                raise RuntimeError(f"Missing distribution RECORD: {name}")
            contents = io.StringIO()
            writer = csv.writer(contents, lineterminator="\n")
            writer.writerows(rows)
            writer.writerow((record_name, "", ""))
            archive.writestr(record_name, contents.getvalue())
