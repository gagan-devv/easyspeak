"""Transcript activation phrase management and matching for EasySpeak.

Provides transcript-based activation ("Apollo", "Hey Apollo", etc.) as an
alternative to the OpenWakeWord model, matching at the start of utterances
using the active speech-to-text backend without requiring cloud services.
"""

import logging
import os
import re
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

ACTIVATION_MODES = ("wakeword", "transcript")

DEFAULT_ACTIVATION_PHRASES = (
    "apollo",
    "hey apollo",
    "ee vee listen",
    "evie listen",
    "e v listen",
    "e.v. listen",
)


def activation_phrases_path() -> Path:
    """Return the user-local path for storing custom activation phrases."""
    return Path.home() / ".config" / "easyspeak" / "activation_phrases.txt"


def normalize_activation_phrase(phrase: str) -> str:
    """Normalize a phrase to lowercase, stripped of surrounding punctuation."""
    if not phrase:
        return ""
    p = phrase.strip().lower()
    # Remove leading/trailing quotes or punctuation
    p = re.sub(r"^[\"'\.,!?\s]+|[\"'\.,!?\s]+$", "", p)
    # Collapse multiple whitespace characters into single space
    return re.sub(r"\s+", " ", p)


def load_activation_phrases(
    phrases_file: Path | None = None,
) -> tuple[tuple[str, ...], str]:
    """Load activation phrases following fallback order: env > file > builtin defaults.

    Returns a tuple of (phrases_tuple, source_name) where source_name is
    "env", "file", or "default".
    """
    env_phrases = os.environ.get("EASYSPEAK_ACTIVATION_PHRASES", "").strip()
    if env_phrases:
        phrases = []
        for raw in env_phrases.split(","):
            norm = normalize_activation_phrase(raw)
            if norm and norm not in phrases:
                phrases.append(norm)
        if phrases:
            return tuple(phrases), "env"

    file_path = phrases_file or activation_phrases_path()
    if file_path.is_file():
        try:
            phrases = []
            for raw_line in file_path.read_text(encoding="utf-8").splitlines():
                # Strip comments and whitespace
                line = raw_line.split("#", 1)[0].strip()
                norm = normalize_activation_phrase(line)
                if norm and norm not in phrases:
                    phrases.append(norm)
            if phrases:
                return tuple(phrases), "file"
        except OSError as e:
            logger.warning(
                "Could not read activation phrases from %s: %s", file_path, e
            )

    return DEFAULT_ACTIVATION_PHRASES, "default"


def match_and_strip_activation(
    text: str, phrases: tuple[str, ...] | list[str] | None = None
) -> tuple[str | None, str]:
    """Check if utterance begins with an activation phrase and extract trailing command.

    Returns (matched_phrase, trailing_command). If not matched, returns (None, "").
    Matching is strictly anchored to the start of the utterance (allowing leading
    filler like 'hey', 'hi', or whitespace/punctuation), preventing mid-utterance
    false activations.
    """
    if not text:
        return None, ""

    if phrases is None:
        phrases, _ = load_activation_phrases()

    if not phrases:
        return None, ""

    # Sort longer phrases first so "hey apollo" matches before "apollo"
    sorted_phrases = sorted(phrases, key=len, reverse=True)
    escaped = [re.escape(p) for p in sorted_phrases]
    # Anchor to start (^), allow optional leading greetings like 'hey ' or 'hi ',
    # followed by the activation phrase and a word boundary, punctuation, or end.
    pattern = rf"^\s*(?:(?:hey|hi|hello)\s+)?(?:{'|'.join(escaped)})(?:\b|[,\.!\?\s]|$)"
    match = re.match(pattern, text, re.IGNORECASE)
    if not match:
        return None, ""

    matched_text = match.group(0).strip(" ,.!?")
    trailing = text[match.end() :].strip(" ,.!?")
    return matched_text, trailing


def activation_preview_text(activation_mode: str | None = None) -> str:
    """Format active activation configuration and phrases for --preview."""
    from . import config

    mode = activation_mode or getattr(config, "ACTIVATION", "wakeword")
    phrases, source = load_activation_phrases()

    lines = [
        f"Activation mode: {mode}",
        f"Configuration source: {source}",
        "Active activation phrases:",
    ]
    for idx, phrase in enumerate(phrases, 1):
        lines.append(f"  {idx}. {phrase}")
    return "\n".join(lines) + "\n"


def configure_activation(
    stdin=None, stdout=None, phrases_file: Path | None = None
) -> bool:
    """Interactive CLI setup for transcript activation phrases.

    Allows listing, adding, removing, testing phrases, and saving to
    ~/.config/easyspeak/activation_phrases.txt.
    """
    in_stream = stdin or sys.stdin
    out_stream = stdout or sys.stdout

    def out(msg: str = ""):
        out_stream.write(msg + "\n")
        out_stream.flush()

    dest_file = phrases_file or activation_phrases_path()
    current_phrases, source = load_activation_phrases(dest_file)
    phrases = list(current_phrases)

    out("EasySpeak Transcript Activation Configuration")
    out(f"Current source: {source} (save will write to {dest_file})")
    out()

    def print_phrases():
        out("Current activation phrases:")
        for idx, phrase in enumerate(phrases, 1):
            out(f"  {idx}. {phrase}")
        out()

    print_phrases()

    while True:
        out(
            "Actions: [a]dd phrase | [r]emove phrase | [t]est utterance | "
            "[l]ist | [s]ave & exit | [q]uit"
        )
        out_stream.write("> ")
        out_stream.flush()

        try:
            line = in_stream.readline()
            if not line:
                out("\nInput closed; exiting without saving.")
                return False
        except (KeyboardInterrupt, EOFError):
            out("\nInterrupted; exiting without saving.")
            return False

        action = line.strip().lower()
        if not action:
            continue

        if action in ("a", "add"):
            out_stream.write("Enter phrase to add: ")
            out_stream.flush()
            new_raw = in_stream.readline()
            norm = normalize_activation_phrase(new_raw)
            if not norm:
                out("Error: activation phrase cannot be empty.")
            elif norm in phrases:
                out(f"Error: phrase '{norm}' is already in the list.")
            else:
                phrases.append(norm)
                out(f"Added: '{norm}'")
            out()

        elif action in ("r", "remove"):
            if len(phrases) <= 1:
                out(
                    "Error: cannot remove the last activation phrase; "
                    "at least one phrase is required."
                )
                out()
                continue
            out_stream.write("Enter phrase number or phrase text to remove: ")
            out_stream.flush()
            rem_raw = in_stream.readline().strip()
            if rem_raw.isdigit():
                idx = int(rem_raw) - 1
                if 0 <= idx < len(phrases):
                    removed = phrases.pop(idx)
                    out(f"Removed: '{removed}'")
                else:
                    out(f"Error: invalid index {rem_raw}.")
            else:
                norm = normalize_activation_phrase(rem_raw)
                if norm in phrases:
                    phrases.remove(norm)
                    out(f"Removed: '{norm}'")
                else:
                    out(f"Error: phrase '{rem_raw}' not found.")
            out()

        elif action in ("t", "test"):
            out_stream.write("Enter sample transcript to test: ")
            out_stream.flush()
            test_utterance = in_stream.readline().strip()
            matched, trailing = match_and_strip_activation(test_utterance, phrases)
            if matched:
                out(
                    f"✓ MATCH! Activation: '{matched}' | Trailing command: '{trailing}'"
                )
            else:
                out("✗ NO MATCH. Utterance must begin with an activation phrase.")
            out()

        elif action in ("l", "list"):
            print_phrases()

        elif action in ("s", "save"):
            try:
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                content = (
                    "# EasySpeak transcript activation phrases\n"
                    "# One phrase per line. Lines starting with # are comments.\n\n"
                    + "\n".join(phrases)
                    + "\n"
                )
                dest_file.write_text(content, encoding="utf-8")
                out(f"Saved {len(phrases)} activation phrases to {dest_file}.")
                return True
            except OSError as e:
                out(f"Error saving to {dest_file}: {e}")
                return False

        elif action in ("q", "quit", "exit"):
            out("Exiting without saving.")
            return False

        else:
            out(f"Unknown action: '{action}'. Choose a, r, t, l, s, or q.")
            out()
