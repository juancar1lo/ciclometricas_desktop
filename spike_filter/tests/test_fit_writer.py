"""Tests para el escritor FIT."""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from spike_filter.fit_writer import rewrite_fit


def _create_test_fit(power_values, tmp_path):
    """Crea un FIT sintético con los valores de potencia dados."""
    from fit_tool.fit_file_builder import FitFileBuilder
    from fit_tool.profile.messages.file_id_message import FileIdMessage
    from fit_tool.profile.messages.record_message import RecordMessage
    from fit_tool.profile.profile_type import FileType, Manufacturer
    import datetime

    base = datetime.datetime(2024, 1, 1, 10, 0, 0, tzinfo=datetime.timezone.utc)
    base_ms = int(base.timestamp() * 1000)

    builder = FitFileBuilder(auto_define=True, min_string_size=0)

    file_id = FileIdMessage()
    file_id.type = FileType.ACTIVITY
    file_id.manufacturer = Manufacturer.DEVELOPMENT.value
    file_id.product = 1
    file_id.serial_number = 12345
    file_id.time_created = base_ms
    builder.add(file_id)

    for i, pw in enumerate(power_values):
        record = RecordMessage()
        record.timestamp = base_ms + i * 1000
        record.power = pw
        record.heart_rate = 120 + i
        builder.add(record)

    fit_file = builder.build()
    out_path = str(tmp_path / "test.fit")
    fit_file.to_file(out_path)
    return out_path


def _read_power_values(fit_path):
    """Lee los valores de potencia de un FIT."""
    import fitdecode
    values = []
    reader = fitdecode.FitReader(open(fit_path, "rb"))
    for frame in reader:
        if isinstance(frame, fitdecode.records.FitDataMessage):
            if frame.mesg_type and frame.mesg_type.mesg_num == 20:
                pw = frame.get_value('power')
                values.append(pw)
    return values


class TestFitWriter:

    def test_rewrite_single_record(self, tmp_path):
        path = _create_test_fit([200, 210, 5500, 230, 200], tmp_path)
        corrections = {2: 215}  # Record 2: 5500 -> 215
        out_path = str(tmp_path / "clean.fit")
        rewrite_fit(path, corrections, out_path)

        values = _read_power_values(out_path)
        assert values == [200, 210, 215, 230, 200]

    def test_rewrite_multiple_records(self, tmp_path):
        path = _create_test_fit([200, 4000, 220, 6000, 200], tmp_path)
        corrections = {1: 210, 3: 210}
        out_path = str(tmp_path / "clean.fit")
        rewrite_fit(path, corrections, out_path)

        values = _read_power_values(out_path)
        assert values == [200, 210, 220, 210, 200]

    def test_no_corrections_preserves(self, tmp_path):
        path = _create_test_fit([200, 210, 220], tmp_path)
        out_path = str(tmp_path / "clean.fit")
        rewrite_fit(path, {}, out_path)

        values = _read_power_values(out_path)
        assert values == [200, 210, 220]

    def test_hr_preserved(self, tmp_path):
        """HR debe preservarse al modificar potencia."""
        path = _create_test_fit([200, 5000, 220], tmp_path)
        corrections = {1: 210}
        out_path = str(tmp_path / "clean.fit")
        rewrite_fit(path, corrections, out_path)

        import fitdecode
        reader = fitdecode.FitReader(open(out_path, "rb"))
        hrs = []
        for frame in reader:
            if isinstance(frame, fitdecode.records.FitDataMessage):
                if frame.mesg_type and frame.mesg_type.mesg_num == 20:
                    hrs.append(frame.get_value('heart_rate'))
        assert hrs == [120, 121, 122]

    def test_returns_bytes(self, tmp_path):
        path = _create_test_fit([200, 5000, 220], tmp_path)
        result = rewrite_fit(path, {1: 210})
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_from_bytes(self, tmp_path):
        path = _create_test_fit([200, 5000, 220], tmp_path)
        raw = open(path, "rb").read()
        out_path = str(tmp_path / "clean.fit")
        rewrite_fit(raw, {1: 210}, out_path)

        values = _read_power_values(out_path)
        assert values == [200, 210, 220]
