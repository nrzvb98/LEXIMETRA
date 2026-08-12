from hala_rt.data.output_paths import default_output_path, next_edited_output_path


def test_default_output_path_stays_next_to_audio():
    output_path = default_output_path("/sessions/p001/trial_01.m4a")

    assert str(output_path) == "/sessions/p001/trial_01_hala_output.csv"


def test_default_output_path_can_use_output_dir(tmp_path):
    output_dir = tmp_path / "outputs"

    output_path = default_output_path("/sessions/p001/trial_01.m4a", output_dir=output_dir)

    assert output_path == output_dir / "trial_01_hala_output.csv"


def test_next_edited_output_path_skips_existing_files(tmp_path):
    base_path = tmp_path / "trial_01_hala_output.csv"
    first_edit = tmp_path / "trial_01_hala_output_edited.csv"
    second_edit = tmp_path / "trial_01_hala_output_edited_2.csv"
    first_edit.write_text("", encoding="utf-8")
    second_edit.write_text("", encoding="utf-8")

    output_path = next_edited_output_path(base_path)

    assert output_path == tmp_path / "trial_01_hala_output_edited_3.csv"

