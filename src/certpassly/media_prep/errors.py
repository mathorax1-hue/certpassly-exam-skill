"""Error taxonomy mapping one-to-one onto the CLI exit-code contract."""
from __future__ import annotations


class MediaPrepError(Exception):
    """Base class. ``exit_code`` selects the documented CLI exit code."""


class ConfigError(MediaPrepError):
    """Invalid config (missing key, bad type, unsafe path). Exit 1."""

    exit_code = 1


class OperationalError(MediaPrepError):
    """Environment/IO failure (missing PDF, unreadable image, broken ZIP). Exit 1."""

    exit_code = 1


class BlockedSourceError(MediaPrepError):
    """A question has no provable clean learner image. Exit 2.

    Never raised as a crash: the CLI collects blocked questions and exits 2
    with the full reason list so automation can act on exact question IDs.
    """

    exit_code = 2


class PrivacyViolationError(MediaPrepError):
    """Privacy/integrity/manifest-tamper refusal. Exit 3, fail-closed."""

    exit_code = 3
