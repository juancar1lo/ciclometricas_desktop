"""Tests para calc/intervals.py."""
from calc.intervals import SampleRow, detect_intervals, DetectIntervalsOptions


class TestDetectIntervals:
    def test_single_interval(self):
        # 30s a 300W, resto a 100W
        samples = (
            [SampleRow(t=float(i), p=100.0) for i in range(50)]
            + [SampleRow(t=float(i), p=300.0) for i in range(50, 100)]
            + [SampleRow(t=float(i), p=100.0) for i in range(100, 200)]
        )
        intervals = detect_intervals(samples, 250)
        assert len(intervals) >= 1
        assert intervals[0].avg_power > 200

    def test_no_intervals_below_threshold(self):
        samples = [SampleRow(t=float(i), p=100.0) for i in range(200)]
        intervals = detect_intervals(samples, 250)
        assert len(intervals) == 0

    def test_multiple_intervals(self):
        samples = []
        for rep in range(3):
            base = rep * 100
            samples += [SampleRow(t=float(base + i), p=300.0) for i in range(30)]
            samples += [SampleRow(t=float(base + 30 + i), p=100.0) for i in range(70)]
        intervals = detect_intervals(samples, 200, DetectIntervalsOptions(min_work_sec=10))
        assert len(intervals) >= 2

    def test_empty(self):
        assert detect_intervals([], 250) == []
