"""An append-only line log the page polls; also a file-like sink for Rich and subprocesses."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass
class LineLog:
    lines: list[str] = field(default_factory=list)
    _partial: str = ""
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def append(self, line: str) -> None:
        with self._lock:
            self.lines.append(line.rstrip("\r\n"))

    def write(self, text: str) -> int:
        """File protocol for Rich's Console: buffer until a newline."""
        with self._lock:
            self._partial += text
            while "\n" in self._partial:
                line, _, self._partial = self._partial.partition("\n")
                self.lines.append(line.rstrip("\r"))
        return len(text)

    def flush(self) -> None:
        with self._lock:
            if self._partial:
                self.lines.append(self._partial.rstrip("\r"))
                self._partial = ""

    def since(self, index: int) -> tuple[list[str], int]:
        with self._lock:
            return self.lines[index:], len(self.lines)
