import json
import random
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mcnp.MCell import MCell
from mcnp.MModel import MModel
from mcnp.MMaterial import MMaterial
from mcnp.MExprParser import parse_geom_expr, collect_surface_ids, decode_facet_id
from mcnp.MSurface import MSurface, MSurfType
from gdml.GDefine import GVector
from gdml.GModel import GModel
from gdml.GSolid import GBooleanSolid, GSphere, GTube
from mcnp2gdml import (
    _compose_pose,
    _eval_surface,
    _parse_transform_from_raw,
    _relative_pose,
    _should_emit_terminal_cell,
    _surface_boundary_pairs,
    mcnp2Gdml,
)


class ParserRegressionTests(unittest.TestCase):
    def test_gdml_primitives_preserve_source_precision(self):
        solids = ET.Element("solids")
        GSphere("s", 6.6595, 6.6495).write_gdml(solids)
        GTube("t", 0.45720, 365.76, 0.40005).write_gdml(solids)
        sphere = solids.find("sphere")
        tube = solids.find("tube")
        self.assertEqual(sphere.get("rmax"), "6.6595")
        self.assertEqual(sphere.get("rmin"), "6.6495")
        self.assertEqual(tube.get("rmax"), "0.4572")
        self.assertEqual(tube.get("rmin"), "0.40005")
        self.assertEqual(tube.get("z"), "365.76")

    def test_cell_option_with_separated_equals(self):
        cell = MCell.create_from_str(
            "10 3 -.5 -18 19 -20 21 imp:n=1 u=4 trcl =7"
        )
        self.assertEqual(cell.universe, 4)
        self.assertEqual(cell.key_opts["TRCL"], "7")
        self.assertEqual(cell.raw_geom_expr, "-18 19 -20 21")

    def test_star_fill_is_removed_from_geometry(self):
        cell = MCell.create_from_str("2 0 -3 -4 *FILL=2 (-7 5 0)")
        self.assertEqual(cell.raw_geom_expr, "-3 -4")
        self.assertIn("FILL", cell.key_opts)
        self.assertTrue(cell.fill.is_star)
        self.assertEqual(cell.fill.universe, 2)
        self.assertEqual(cell.fill.transform, "-7 5 0")

    def test_simple_fill_transform_is_parsed(self):
        cell = MCell.create_from_str("2 0 -1 fill=3 (1 2 3)")
        self.assertEqual(cell.fill.universe, 3)
        self.assertEqual(cell.fill.transform, "1 2 3")
        self.assertFalse(cell.fill.is_star)

    def test_indexed_fill_entry_transforms_and_repeats_are_parsed(self):
        cell = MCell.create_from_str(
            "4 0 -1 lat=1 fill=-1:1 0:0 2(3) 4 ( 5 0 0 ) 2R"
        )
        self.assertEqual(cell.fill.ranges, ((-1, 1), (0, 0)))
        self.assertEqual(cell.fill.entries, (2, 4, 4, 4))
        self.assertEqual(cell.fill.entry_transforms, ("3", "5 0 0", "5 0 0", "5 0 0"))

    def test_star_fill_six_angles_complete_rotation_matrix(self):
        pos, rot = _parse_transform_from_raw(
            "-7 5 0 30 60 90 120 30 90", {}, is_star=True
        )
        self.assertEqual(pos, (-7.0, 5.0, 0.0))
        self.assertAlmostEqual(rot[0], 0.0, places=8)
        self.assertAlmostEqual(rot[1], 0.0, places=8)
        self.assertAlmostEqual(rot[2], 30.0, places=8)

    def test_relative_pose_round_trips_through_parent(self):
        parent_pos = (10.0, -4.0, 7.0)
        parent_rot = (12.0, -23.0, 37.0)
        child_pos = (-2.0, 8.0, 3.5)
        child_rot = (-15.0, 9.0, 71.0)
        relative_pos, relative_rot = _relative_pose(
            parent_pos, parent_rot, child_pos, child_rot
        )
        composed_pos, composed_rot = _compose_pose(
            parent_pos, parent_rot, relative_pos, relative_rot
        )
        for actual, expected in zip(composed_pos, child_pos):
            self.assertAlmostEqual(actual, expected, places=8)
        for actual, expected in zip(composed_rot, child_rot):
            self.assertAlmostEqual(actual, expected, places=8)

    def test_boolean_inline_transforms_have_unique_xsd_ids(self):
        solid = GBooleanSolid(
            "Bool_7",
            "intersection",
            "A",
            "B",
            GVector("shared", "position", "cm", 1, 2, 3),
            GVector("shared", "rotation", "deg", 4, 5, 6),
        )
        parent = ET.Element("solids")
        solid.write_gdml(parent)
        node = parent[0]
        self.assertEqual(node.find("position").get("name"), "Pos_Bool_7")
        self.assertEqual(node.find("rotation").get("name"), "Rot_Bool_7")

    def test_sphere_aliases_are_canonicalized(self):
        cases = {
            "7 S 1 2 3 4": [1.0, 2.0, 3.0, 4.0],
            "7 SX 1 4": [1.0, 0.0, 0.0, 4.0],
            "7 SY 2 4": [0.0, 2.0, 0.0, 4.0],
            "7 SZ 3 4": [0.0, 0.0, 3.0, 4.0],
        }
        for card, params in cases.items():
            with self.subTest(card=card):
                surf = MSurface.create_from_str(card)
                self.assertEqual(surf.stype, MSurfType.SPH)
                self.assertEqual(surf.params, params)

    def test_surface_transform_and_boundary_are_preserved(self):
        surf = MSurface.create_from_str("*89 4 P 1 0 0 5")
        self.assertEqual(surf.sid, 89)
        self.assertEqual(surf.stype, MSurfType.P)
        self.assertEqual(surf.transform_id, 4)
        self.assertEqual(surf.boundary, "*")

    def test_torus_surface_types(self):
        for stype in ("TX", "TY", "TZ"):
            with self.subTest(stype=stype):
                surf = MSurface.create_from_str(f"9 {stype} 1 2 3 10 4 4")
                self.assertEqual(surf.stype, MSurfType[stype])
                self.assertEqual(surf.params, [1.0, 2.0, 3.0, 10.0, 4.0, 4.0])

    def test_sq_surface_is_parsed(self):
        surf = MSurface.create_from_str("17 SQ 1 2 0 0 0 0 -1 .2 0 0")
        self.assertEqual(surf.stype, MSurfType.SQ)
        self.assertEqual(len(surf.params), 10)

    def test_three_point_x_surface_becomes_ellipsoid(self):
        surf = MSurface.create_from_str("13 X -4.5 0 -.5 1.7 3.5 0")
        self.assertEqual(surf.stype, MSurfType.ELL_G)
        self.assertEqual(len(surf.params), 15)
        self.assertEqual(surf.params[0:3], [-0.5, 0.0, 0.0])
        self.assertEqual(surf.params[12:15], [4.0, 1.7, 1.7])

    def test_trc_surface_is_parsed(self):
        surf = MSurface.create_from_str("7 TRC 0 0 0 0 200 0 .25 7.5")
        self.assertEqual(surf.stype, MSurfType.TRC)
        self.assertEqual(len(surf.params), 8)

    def test_axis_and_offset_cones_are_parsed(self):
        self.assertEqual(MSurface.create_from_str("1 KZ 3 0.25 1").stype, MSurfType.KZ)
        self.assertEqual(MSurface.create_from_str("2 K/Z 1 2 3 0.25 -1").stype, MSurfType.K_Z)

    def test_star_transform_angles_form_direction_cosines(self):
        vals = [0.0, 0.0, 0.0, 0.0, 90.0, 90.0, 90.0, 0.0, 90.0, 90.0, 90.0, 0.0]
        transform = MModel._parse_transform_vals(vals, is_star=True)
        for value in transform["rot"]:
            self.assertAlmostEqual(value, 0.0, places=8)

    def test_transformed_plane_is_canonical_global_plane(self):
        surf = MSurface.create_from_str("7 3 PX 2")
        global_surf = MModel._surface_to_global(
            surf, {"pos": (10.0, 0.0, 0.0), "rot": (0.0, 0.0, 90.0)}
        )
        self.assertEqual(global_surf.stype, MSurfType.P)
        self.assertAlmostEqual(global_surf.params[0], 0.0, places=8)
        self.assertAlmostEqual(global_surf.params[1], 1.0, places=8)
        self.assertAlmostEqual(global_surf.params[2], 0.0, places=8)
        self.assertAlmostEqual(global_surf.params[3], 2.0, places=8)
        self.assertIsNone(global_surf.transform_id)

    def test_transformed_rpp_becomes_oriented_box(self):
        surf = MSurface.create_from_str("8 2 RPP 0 2 0 4 0 6")
        global_surf = MModel._surface_to_global(
            surf, {"pos": (1.0, 2.0, 3.0), "rot": (0.0, 0.0, 90.0)}
        )
        self.assertEqual(global_surf.stype, MSurfType.BOX)
        self.assertEqual(len(global_surf.params), 12)
        self.assertAlmostEqual(global_surf.params[0], 1.0, places=8)
        self.assertAlmostEqual(global_surf.params[1], 2.0, places=8)
        self.assertAlmostEqual(global_surf.params[2], 3.0, places=8)

    def test_material_options_do_not_break_fraction_pairs(self):
        mat = MMaterial.create_from_str("M1 1001.31c -0.5 8016.31c -0.5 PLIB=84P")
        self.assertEqual(len(mat.fractions), 2)
        self.assertAlmostEqual(sum(mat.fractions.values()), -1.0)

    def test_zero_padded_zaid_has_canonical_id_and_atomic_mass(self):
        mat = MMaterial.create_from_str("M13 002003.00c 0.1 054136.00c 0.9")
        elements = list(mat.fractions)
        self.assertEqual([elem.name for elem in elements], ["002003", "054136"])
        self.assertTrue(all(elem.mass > 0.0 for elem in elements))

    def test_importance_interpolation_and_repeat(self):
        vals = MModel._expand_numeric_card(["1", "2I", "0", "2R"])
        self.assertEqual(len(vals), 6)
        self.assertAlmostEqual(vals[1], 2.0 / 3.0)
        self.assertEqual(vals[-2:], [0.0, 0.0])

    def test_macrobody_facet_reference_is_encoded(self):
        ast = parse_geom_expr("-37 40.1")
        ids = collect_surface_ids(ast)
        decoded = [decode_facet_id(value) for value in ids if decode_facet_id(value)]
        self.assertEqual(decoded, [(40, 1)])

    def test_universe_option_without_equals(self):
        cell = MCell.create_from_str("1 0 -1 u 3")
        self.assertEqual(cell.universe, 3)
        self.assertEqual(cell.raw_geom_expr, "-1")

    def test_integral_float_void_material_id(self):
        cell = MCell.create_from_str("55 0.00000 -1 2")
        self.assertEqual(cell.mat_id, 0)

    def test_terminal_void_is_world_material_in_mixed_deck(self):
        void_cell = MCell.create_from_str("1 0 5")
        material_cell = MCell.create_from_str("2 1 -1.0 -5")
        self.assertFalse(_should_emit_terminal_cell(void_cell, has_material_cells=True))
        self.assertTrue(_should_emit_terminal_cell(material_cell, has_material_cells=True))
        self.assertTrue(_should_emit_terminal_cell(void_cell, has_material_cells=False))

    def test_message_continue_preamble_is_not_parsed_as_geometry(self):
        """Published MCNP decks may omit a title card via MESSAGE: / CONTINUE."""
        deck = """MESSAGE:

CONTINUE
1 1 -1.0 -1 imp:n=1
2 0 1 imp:n=0

1 so 10

m1 1001 2 8016 1
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "message_preamble.i"
            source.write_text(deck, encoding="utf-8")
            model = MModel()
            model.read_from_file(source)
        self.assertEqual(len(model.cells), 2)
        self.assertEqual(len(model.surfaces), 1)
        self.assertEqual(len(model.materials), 1)

    def test_transformed_surface_alias_uses_owning_cell_trcl(self):
        """MCNP's cell-id/surface-id aliases must retain the source TRCL pose."""
        deck = """transformed surface alias
1 1 -1.0 -1 2 -3 4 trcl=1 imp:n=1
2 0 -1001 2 -3 4 imp:n=1
3 0 1:-2:3:-4 imp:n=0

1 px 0
2 px 20
3 py -10
4 py 10

tr1 5 0 0
m1 1001 1
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "surface_alias.i"
            output = Path(tmpdir) / "surface_alias.gdml"
            source.write_text(deck, encoding="utf-8")
            model = MModel()
            model.read_from_file(source)
            GModel._instance = None
            gdml = GModel()
            mcnp2Gdml(model, gdml, [], None, 0.1, False)
            gdml.write_gdml(output)
            root = ET.parse(output).getroot()

        clip = root.find("solids").find("intersection[@name='Clip_1_off_9']")
        self.assertIsNotNone(clip)
        self.assertAlmostEqual(float(clip.find("position").get("x")), 5.0)

    def test_fridge_indexed_hex_lattice_expands(self):
        """The published FRIDGe assembly exercises indexed MCNP LAT=2 fills."""
        source = (
            Path(__file__).resolve().parent
            / "engineering_cases/FRIDGe-1.0.1/FRIDGe-1.0.1/fridge/mcnp_input_files"
            / "Prefab_Fuel_Assembly_Test.i"
        )
        model = MModel()
        model.read_from_file(source)
        GModel._instance = None
        gdml = GModel()
        mcnp2Gdml(model, gdml, [], None, 0.1, False)
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "fridge.gdml"
            gdml.write_gdml(output)
            root = ET.parse(output).getroot()
        volumes = root.find("structure").findall("volume")
        names = {volume.get("name") for volume in volumes}
        self.assertGreater(len(volumes), 800)
        self.assertTrue(any(name.startswith("Vol_100_") for name in names))
        self.assertTrue(any(name.startswith("Vol_103_") for name in names))

    def test_boundary_probe_generator_brackets_common_surfaces(self):
        bbox = {"cx": 0.0, "cy": 0.0, "cz": 0.0, "hx": 10.0, "hy": 10.0, "hz": 10.0}
        rng = random.Random(7)
        surfaces = [
            MSurface(1, MSurfType.PX, [2.0]),
            MSurface(2, MSurfType.CZ, [3.0]),
            MSurface(3, MSurfType.SO, [4.0]),
            MSurface(4, MSurfType.RPP, [-2.0, 2.0, -3.0, 3.0, -4.0, 4.0]),
        ]
        for surface in surfaces:
            with self.subTest(surface=surface.sid):
                pairs = _surface_boundary_pairs(surface, bbox, 12, 1e-4, rng)
                self.assertGreaterEqual(len(pairs), 6)
                for minus, plus in pairs:
                    minus_inside = _eval_surface(surface, -1, minus, 1e-8)
                    plus_inside = _eval_surface(surface, -1, plus, 1e-8)
                    self.assertNotEqual(minus_inside, plus_inside)

    def test_layered_validation_reports_active_boundary_pairs(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "examples/seven_hole_disk/seven_hole_disk.i"
        )
        model = MModel()
        model.read_from_file(source)
        GModel._instance = None
        gdml = GModel()
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "validation.json"
            validate = {
                "samples": 20,
                "local_samples": 20,
                "boundary_samples": 8,
                "seed": 0,
                "eps": 1e-6,
                "cells": [1],
                "out_path": str(report_path),
            }
            mcnp2Gdml(model, gdml, [1], None, 0.1, False, False, validate)
            report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["schema_version"], 2)
        self.assertEqual(report["totals"]["mismatches"], 0)
        self.assertGreater(report["totals"]["boundary_pairs"], 0)
        self.assertGreater(report["totals"]["active_boundary_pairs"], 0)

    def test_general_plane_far_from_explicit_domain_preserves_retained_bbox(self):
        """A finite P cutter must not miss a user-supplied domain far from it."""
        cases = (
            ("negative_axis", "-1", "1 P 1 0 0 2000"),
            ("positive_axis", "1", "1 P 1 0 0 -2000"),
            ("negative_oblique", "-1", "1 P 1 1 1 2000"),
        )
        for label, region, surface in cases:
            with self.subTest(label=label):
                deck = f"""general plane outside declared domain
1 0 {region} imp:n=1

{surface}
"""
                with tempfile.TemporaryDirectory() as tmpdir:
                    source = Path(tmpdir) / f"{label}.i"
                    report_path = Path(tmpdir) / f"{label}.validate.json"
                    source.write_text(deck, encoding="utf-8")
                    model = MModel()
                    model.read_from_file(source)
                    GModel._instance = None
                    gdml = GModel()
                    validate = {
                        "samples": 20,
                        "local_samples": 20,
                        "boundary_samples": 0,
                        "seed": 0,
                        "eps": 1e-6,
                        "cells": [1],
                        "out_path": str(report_path),
                    }
                    mcnp2Gdml(
                        model,
                        gdml,
                        [1],
                        (-10.0, 10.0, -10.0, 10.0, -10.0, 10.0),
                        0.1,
                        False,
                        False,
                        validate,
                    )
                    report = json.loads(report_path.read_text(encoding="utf-8"))
                self.assertEqual(report["totals"]["points"], 40)
                self.assertEqual(report["totals"]["mismatches"], 0)


if __name__ == "__main__":
    unittest.main()
