import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "summarize_corpus_coverage.py"
SPEC = importlib.util.spec_from_file_location("summarize_corpus_coverage", MODULE_PATH)
coverage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(coverage)

BENCHMARK_PATH = ROOT / "tools" / "benchmark_conversion.py"
BENCHMARK_SPEC = importlib.util.spec_from_file_location("benchmark_conversion", BENCHMARK_PATH)
benchmark = importlib.util.module_from_spec(BENCHMARK_SPEC)
BENCHMARK_SPEC.loader.exec_module(benchmark)


class CorpusSummaryTests(unittest.TestCase):
    def test_summary_separates_geometry_and_material_qualifications(self):
        manifest = {
            "schema_version": 2,
            "coverage": [
                {
                    "cells": 2,
                    "surfaces": 3,
                    "surface_histogram": {"PX": 3},
                    "union": 1,
                    "baseline_converted": True,
                    "baseline_xml_well_formed": True,
                    "baseline_gdml_integrity_valid": True,
                    "baseline_warning_count": 0,
                    "baseline_warning_categories": {},
                },
                {
                    "cells": 1,
                    "surfaces": 2,
                    "surface_histogram": {"TZ": 2},
                    "lattice": 1,
                    "baseline_converted": True,
                    "baseline_xml_well_formed": True,
                    "baseline_gdml_integrity_valid": True,
                    "baseline_warning_count": 1,
                    "baseline_warning_categories": {"other": 1},
                },
                {
                    "cells": 1,
                    "surfaces": 1,
                    "surface_histogram": {"SO": 1},
                    "baseline_converted": True,
                    "baseline_xml_well_formed": True,
                    "baseline_gdml_integrity_valid": True,
                    "baseline_warning_count": 1,
                    "baseline_warning_categories": {"source_material_missing": 1},
                },
            ],
        }
        summary = coverage.build_summary(manifest)
        self.assertEqual(summary["cases"], 3)
        self.assertEqual(summary["surface_histogram"], {"PX": 3, "SO": 1, "TZ": 2})
        self.assertEqual(summary["baseline"]["warning_free"], 1)
        self.assertEqual(summary["baseline"]["geometry_degradation_free"], 2)
        self.assertEqual(summary["baseline"]["source_material_complete"], 2)

    def test_benchmark_case_parser_accepts_optional_top_cells(self):
        label, source, top_cells = benchmark.parse_case("spent|test/deck.i|1051")
        self.assertEqual((label, source, top_cells), ("spent", Path("test/deck.i"), "1051"))
        label, source, top_cells = benchmark.parse_case("case10|test/CASE_10")
        self.assertEqual((label, source, top_cells), ("case10", Path("test/CASE_10"), ""))


if __name__ == "__main__":
    unittest.main()
