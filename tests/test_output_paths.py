from leximetra.data.output_paths import (
    default_output_path,
    next_edited_output_path,
    resolve_output_path,
)


def test_default_output_path_stays_next_to_audio():
    output_path = default_output_path("/sessions/p001/trial_01.m4a")

    assert str(output_path) == "/sessions/p001/trial_01_output.csv"


def test_default_output_path_can_use_output_dir(tmp_path):
    output_dir = tmp_path / "outputs"

    output_path = default_output_path("/sessions/p001/trial_01.m4a", output_dir=output_dir)

    assert output_path == output_dir / "trial_01_output.csv"


def test_next_edited_output_path_skips_existing_files(tmp_path):
    base_path = tmp_path / "trial_01_output.csv"
    first_edit = tmp_path / "trial_01_output_edited.csv"
    second_edit = tmp_path / "trial_01_output_edited_2.csv"
    first_edit.write_text("", encoding="utf-8")
    second_edit.write_text("", encoding="utf-8")

    output_path = next_edited_output_path(base_path)

    assert output_path == tmp_path / "trial_01_output_edited_3.csv"


def test_resolve_prefers_current_name_even_without_a_file(tmp_path):
    audio = tmp_path / "trial_01.m4a"

    assert resolve_output_path(audio) == tmp_path / "trial_01_output.csv"


def test_resolve_falls_back_to_legacy_csv(tmp_path):
    """A CSV verified under a 0.2.x release must keep loading."""
    audio = tmp_path / "trial_01.m4a"
    legacy = tmp_path / "trial_01_hala_output.csv"
    legacy.write_text("", encoding="utf-8")

    assert resolve_output_path(audio) == legacy


def test_resolve_prefers_current_name_over_legacy(tmp_path):
    audio = tmp_path / "trial_01.m4a"
    current = tmp_path / "trial_01_output.csv"
    current.write_text("", encoding="utf-8")
    (tmp_path / "trial_01_hala_output.csv").write_text("", encoding="utf-8")

    assert resolve_output_path(audio) == current
