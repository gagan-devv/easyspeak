"""Unit tests for transcript activation, phrase management, and CLI configuration."""

import io

from easyspeak.core import activation


class TestNormalizeActivationPhrase:
    """Tests for activation phrase normalization."""

    def test_lowercase_and_strip(self):
        assert activation.normalize_activation_phrase("  Apollo  ") == "apollo"
        assert activation.normalize_activation_phrase("Hey Apollo") == "hey apollo"

    def test_strip_outer_punctuation(self):
        assert activation.normalize_activation_phrase('"Apollo"') == "apollo"
        assert activation.normalize_activation_phrase("Apollo!") == "apollo"
        assert (
            activation.normalize_activation_phrase("  Hey, Apollo?  ") == "hey, apollo"
        )

    def test_collapse_spaces(self):
        assert (
            activation.normalize_activation_phrase("ee   vee   listen")
            == "ee vee listen"
        )

    def test_empty_string(self):
        assert activation.normalize_activation_phrase("") == ""
        assert activation.normalize_activation_phrase("   ") == ""


class TestLoadActivationPhrases:
    """Tests for fallback order: env > file > builtin defaults."""

    def test_default_phrases(self, monkeypatch, tmp_path):
        monkeypatch.delenv("EASYSPEAK_ACTIVATION_PHRASES", raising=False)
        non_existent = tmp_path / "does_not_exist.txt"
        phrases, source = activation.load_activation_phrases(non_existent)
        assert source == "default"
        assert "apollo" in phrases
        assert "ee vee listen" in phrases

    def test_file_phrases(self, monkeypatch, tmp_path):
        monkeypatch.delenv("EASYSPEAK_ACTIVATION_PHRASES", raising=False)
        phrases_file = tmp_path / "activation_phrases.txt"
        phrases_file.write_text(
            "# Custom phrases\n"
            "computer # Star Trek style\n"
            "\n"
            "jarvis assistant\n"
            "computer\n",  # duplicate should be filtered
            encoding="utf-8",
        )
        phrases, source = activation.load_activation_phrases(phrases_file)
        assert source == "file"
        assert phrases == ("computer", "jarvis assistant")

    def test_env_overrides_file_and_default(self, monkeypatch, tmp_path):
        monkeypatch.setenv("EASYSPEAK_ACTIVATION_PHRASES", "apollo, my bot, apollo")
        phrases_file = tmp_path / "activation_phrases.txt"
        phrases_file.write_text("file_phrase\n", encoding="utf-8")

        phrases, source = activation.load_activation_phrases(phrases_file)
        assert source == "env"
        assert phrases == ("apollo", "my bot")


class TestMatchAndStripActivation:
    """Tests for utterance matching and mid-utterance false-positive prevention."""

    def test_start_of_utterance_match(self):
        matched, cmd = activation.match_and_strip_activation(
            "Apollo open files", phrases=("apollo", "ee vee listen")
        )
        assert matched == "Apollo"
        assert cmd == "open files"

    def test_start_with_punctuation(self):
        matched, cmd = activation.match_and_strip_activation(
            "Apollo, open documents.", phrases=("apollo", "ee vee listen")
        )
        assert matched == "Apollo"
        assert cmd == "open documents"

    def test_leading_greetings_allowed(self):
        matched, cmd = activation.match_and_strip_activation(
            "Hey Apollo open files", phrases=("apollo", "ee vee listen")
        )
        assert matched is not None
        assert "Apollo" in matched
        assert cmd == "open files"

    def test_bare_activation_phrase(self):
        matched, cmd = activation.match_and_strip_activation(
            "Apollo", phrases=("apollo", "ee vee listen")
        )
        assert matched == "Apollo"
        assert cmd == ""

    def test_mid_utterance_does_not_wake(self):
        """Utterances containing the phrase in the middle or end must NOT trigger activation."""
        matched, cmd = activation.match_and_strip_activation(
            "and I said Apollo open files", phrases=("apollo", "ee vee listen")
        )
        assert matched is None
        assert cmd == ""

        matched, cmd = activation.match_and_strip_activation(
            "the movie Apollo 13 is good", phrases=("apollo", "ee vee listen")
        )
        assert matched is None
        assert cmd == ""

    def test_unrelated_speech_does_not_wake(self):
        matched, cmd = activation.match_and_strip_activation(
            "open browser", phrases=("apollo", "ee vee listen")
        )
        assert matched is None
        assert cmd == ""


class TestConfigureActivationCLI:
    """Tests for interactive --configure activation CLI."""

    def test_add_and_save_phrase(self, tmp_path, monkeypatch):
        monkeypatch.delenv("EASYSPEAK_ACTIVATION_PHRASES", raising=False)
        dest_file = tmp_path / "activation_phrases.txt"
        # Input sequence:
        # a (add) -> my assistant -> s (save)
        inputs = "a\nmy assistant\ns\n"
        stdin = io.StringIO(inputs)
        stdout = io.StringIO()

        saved = activation.configure_activation(
            stdin=stdin, stdout=stdout, phrases_file=dest_file
        )
        assert saved is True
        assert dest_file.is_file()
        content = dest_file.read_text()
        assert "my assistant" in content

    def test_remove_phrase_protects_last_phrase(self, tmp_path, monkeypatch):
        monkeypatch.delenv("EASYSPEAK_ACTIVATION_PHRASES", raising=False)
        dest_file = tmp_path / "activation_phrases.txt"
        # Seed with one phrase only
        dest_file.write_text("onlyone\n", encoding="utf-8")

        inputs = "r\nq\n"
        stdin = io.StringIO(inputs)
        stdout = io.StringIO()

        saved = activation.configure_activation(
            stdin=stdin, stdout=stdout, phrases_file=dest_file
        )
        assert saved is False
        output = stdout.getvalue()
        assert "cannot remove the last activation phrase" in output

    def test_remove_phrase_by_index_and_save(self, tmp_path, monkeypatch):
        monkeypatch.delenv("EASYSPEAK_ACTIVATION_PHRASES", raising=False)
        dest_file = tmp_path / "activation_phrases.txt"
        dest_file.write_text("first\nsecond\nthird\n", encoding="utf-8")

        # Remove index 2 ("second"), then save
        inputs = "r\n2\ns\n"
        stdin = io.StringIO(inputs)
        stdout = io.StringIO()

        saved = activation.configure_activation(
            stdin=stdin, stdout=stdout, phrases_file=dest_file
        )
        assert saved is True
        content = dest_file.read_text()
        assert "second" not in content
        assert "first" in content
        assert "third" in content

    def test_test_phrase_action(self, tmp_path, monkeypatch):
        monkeypatch.delenv("EASYSPEAK_ACTIVATION_PHRASES", raising=False)
        dest_file = tmp_path / "activation_phrases.txt"
        dest_file.write_text("apollo\n", encoding="utf-8")

        inputs = "t\nApollo open browser\nt\nrandom speech\nq\n"
        stdin = io.StringIO(inputs)
        stdout = io.StringIO()

        activation.configure_activation(
            stdin=stdin, stdout=stdout, phrases_file=dest_file
        )
        output = stdout.getvalue()
        assert "✓ MATCH!" in output
        assert "✗ NO MATCH." in output


class TestActivationPreview:
    """Tests for --preview activation output."""

    def test_preview_output(self, monkeypatch):
        monkeypatch.setenv("EASYSPEAK_ACTIVATION_PHRASES", "apollo, test phrase")
        preview = activation.activation_preview_text(activation_mode="transcript")
        assert "Activation mode: transcript" in preview
        assert "Configuration source: env" in preview
        assert "apollo" in preview
        assert "test phrase" in preview
