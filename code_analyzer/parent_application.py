# code_analyzer/parent_application.py
"""The Parent Application of a web application.

A web application is a project file that declares an IIS URL. Visual Studio
writes the IIS URL into the web project extension of the project file. IIS
runs a child application below the URL of its Parent Application, and the
child inherits the configuration of the parent.

Project A is the Parent Application of project B when both IIS URLs have the
same scheme, host, and port, and the path of A is a proper prefix of the path
of B at a segment boundary. The comparison ignores case and a trailing slash.
The nearest ancestor has the longest path. When two projects have that longest
path, the result is ambiguous and gives no Parent Application.

This module reads the project files only. It never reads the code of an
ancestor. It uses no System name, no path, and no Database name.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union
from urllib.parse import urlsplit

from .project_connection_scope import IGNORED_DIRECTORY_NAMES, PROJECT_FILE_SUFFIXES

_DEFAULT_PORTS = {"http": 80, "https": 443}


@dataclass(frozen=True)
class IisUrl:
    """An IIS URL, reduced to the parts that the comparison uses."""

    origin: Tuple[str, str, Optional[int]]
    segments: Tuple[str, ...]


def parse_iis_url(text: str) -> Optional[IisUrl]:
    """The parts of an IIS URL. Gives None when the text is not a web address."""
    try:
        parts = urlsplit(text.strip())
        port = parts.port
    except ValueError:
        return None
    scheme = parts.scheme.casefold()
    host = (parts.hostname or "").casefold()
    if scheme not in _DEFAULT_PORTS or not host:
        return None
    segments = tuple(
        segment.casefold() for segment in parts.path.split("/") if segment
    )
    return IisUrl(
        origin=(scheme, host, port if port is not None else _DEFAULT_PORTS[scheme]),
        segments=segments,
    )


def read_iis_url(project_file: Union[str, Path]) -> Optional[IisUrl]:
    """The IIS URL that a project file declares, or None.

    The element can sit in an XML namespace, so the search compares the local
    name only.
    """
    try:
        root = ET.parse(project_file).getroot()
    except (ET.ParseError, OSError, UnicodeDecodeError):
        return None
    for element in root.iter():
        tag = element.tag if isinstance(element.tag, str) else ""
        if tag.rsplit("}", 1)[-1] == "IISUrl" and (element.text or "").strip():
            return parse_iis_url(element.text or "")
    return None


def _is_proper_prefix(ancestor: IisUrl, descendant: IisUrl) -> bool:
    return (
        ancestor.origin == descendant.origin
        and len(ancestor.segments) < len(descendant.segments)
        and descendant.segments[: len(ancestor.segments)] == ancestor.segments
    )


class ParentApplications:
    """The web applications of one repository clone.

    The first question reads each project file of the clone one time. A
    question about a project with no IIS URL does not read the clone.
    """

    def __init__(self, clone_root: Optional[Path]):
        self._clone_root = clone_root
        self._applications: Optional[Dict[Path, IisUrl]] = None
        self._urls: Dict[Path, Optional[IisUrl]] = {}

    def iis_url_of(self, project_file: Path) -> Optional[IisUrl]:
        """The IIS URL of a project file, or None."""
        if project_file not in self._urls:
            self._urls[project_file] = read_iis_url(project_file)
        return self._urls[project_file]

    def parent_of(self, project_file: Path) -> Optional[Path]:
        """The Parent Application of a project, or None.

        Gives None when the project has no IIS URL, when the analyzer finds no
        clone root, when no project qualifies, and when the nearest ancestor is
        ambiguous.
        """
        if self._clone_root is None:
            return None
        own = self.iis_url_of(project_file)
        if own is None:
            return None
        candidates = [
            (url, path)
            for path, url in self._web_applications().items()
            if path != project_file and _is_proper_prefix(url, own)
        ]
        if not candidates:
            return None
        longest = max(len(url.segments) for url, _ in candidates)
        nearest = sorted(path for url, path in candidates if len(url.segments) == longest)
        return nearest[0] if len(nearest) == 1 else None

    def chain_of(self, project_file: Path) -> List[Path]:
        """The Parent Applications of a project, nearest first."""
        chain: List[Path] = []
        current: Optional[Path] = project_file
        while current is not None:
            current = self.parent_of(current)
            if current is None or current in chain or current == project_file:
                break
            chain.append(current)
        return chain

    def _web_applications(self) -> Dict[Path, IisUrl]:
        if self._applications is None:
            self._applications = {}
            for project_file in self._project_files():
                url = self.iis_url_of(project_file)
                if url is not None:
                    self._applications[project_file] = url
        return self._applications

    def _project_files(self) -> List[Path]:
        found: List[Path] = []
        for directory, directory_names, file_names in os.walk(self._clone_root):
            directory_names[:] = sorted(
                name
                for name in directory_names
                if name.casefold() not in IGNORED_DIRECTORY_NAMES
            )
            found.extend(
                Path(directory) / name
                for name in sorted(file_names)
                if name.casefold().endswith(PROJECT_FILE_SUFFIXES)
            )
        return found
