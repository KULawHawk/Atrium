"""Per-aim learning folders for the APEX suite (design: learning-folders/DESIGN_learning_folders_2026-11-22.md).

Standard library only. The installer creates ``<root>\\learning\\<aim>\\``; this package adds items,
moves them aside, reads the manifest, and holds the per-aim "add automatically" switch (off by default).
It has no rules of its own about what is safe: each aim hands in its own gate.
"""

from atrium_learning.folder import (
    ADD_BACK_DAYS,
    AIMS,
    CLASSES,
    HOLD_REASONS,
    SUBFOLDERS,
    GateResult,
    LearningFolder,
    LearningFolderError,
    add_back_warning,
    find_install_root,
)

__all__ = [
    "ADD_BACK_DAYS",
    "AIMS",
    "CLASSES",
    "HOLD_REASONS",
    "SUBFOLDERS",
    "GateResult",
    "LearningFolder",
    "LearningFolderError",
    "add_back_warning",
    "find_install_root",
]
