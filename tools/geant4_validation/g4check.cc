#include "G4GDMLParser.hh"
#include "G4AffineTransform.hh"
#include "G4GeometryManager.hh"
#include "G4LogicalVolume.hh"
#include "G4LogicalVolumeStore.hh"
#include "G4Material.hh"
#include "G4Navigator.hh"
#include "G4PhysicalVolumeStore.hh"
#include "G4SolidStore.hh"
#include "G4StateManager.hh"
#include "G4SystemOfUnits.hh"
#include "G4VExceptionHandler.hh"
#include "G4VPhysicalVolume.hh"
#include "G4VSolid.hh"

#include <cstdlib>
#include <fstream>
#include <iostream>
#include <algorithm>
#include <cmath>
#include <limits>
#include <random>
#include <set>
#include <sstream>
#include <string>
#include <tuple>
#include <vector>

class OverlapExceptionHandler final : public G4VExceptionHandler {
 public:
  int overlap_events = 0;
  int invalid_surface_events = 0;
  int other_warning_events = 0;
  std::vector<std::string> overlap_descriptions;

  G4bool Notify(const char*, const char*, G4ExceptionSeverity severity,
                const char* description) override {
    const std::string message = description == nullptr ? "" : description;
    if (message.find("Overlap with volume already placed") != std::string::npos ||
        message.find("protruding from its mother") != std::string::npos) {
      ++overlap_events;
      if (overlap_descriptions.size() < 20) {
        std::string concise = message;
        for (char& ch : concise) {
          if (ch == '\n' || ch == '\r') ch = ' ';
        }
        overlap_descriptions.push_back(concise);
      }
    } else if (message.find("Sample point is not on the surface") != std::string::npos ||
               message.find("attempts to generate a point on the surface have failed") !=
                   std::string::npos) {
      ++invalid_surface_events;
    } else {
      ++other_warning_events;
    }
    return severity == FatalException || severity == FatalErrorInArgument;
  }
};

struct PlacedSolid {
  G4VPhysicalVolume* physical;
  G4VSolid* solid;
  G4AffineTransform transform;
  G4ThreeVector local_min;
  G4ThreeVector local_max;
  G4ThreeVector global_min;
  G4ThreeVector global_max;
};

struct InteriorOverlapResult {
  int overlap_volumes = 0;
  int overlap_pairs = 0;
  int sampling_failed_volumes = 0;
  int sampling_incomplete_volumes = 0;
  long long accepted_points = 0;
  int tolerance_suppressed_pairs = 0;
};

struct PointClassificationResult {
  long long queries = 0;
  long long mismatches = 0;
  long long missing_solids = 0;
};

struct NavigationResult {
  long long queries = 0;
  long long mismatches = 0;
  long long unresolved = 0;
};

PointClassificationResult CheckPointClassifications(const std::string& path) {
  PointClassificationResult result;
  if (path.empty()) return result;
  std::ifstream input(path);
  if (!input) {
    std::cerr << "MCGEOBRIDGE_ERROR point_file_unreadable path=" << path << "\n";
    result.missing_solids = 1;
    return result;
  }
  std::string line;
  std::getline(input, line);  // header
  int reports = 0;
  while (std::getline(input, line)) {
    if (line.empty()) continue;
    std::istringstream fields(line);
    std::string solid_name;
    std::string strategy;
    int cell_id = 0;
    double x = 0.0;
    double y = 0.0;
    double z = 0.0;
    int expected = 0;
    if (!(fields >> solid_name >> x >> y >> z >> expected >> strategy >> cell_id)) {
      continue;
    }
    ++result.queries;
    G4VSolid* solid = nullptr;
    for (auto* candidate : *G4SolidStore::GetInstance()) {
      if (candidate->GetName() == solid_name) {
        solid = candidate;
        break;
      }
    }
    if (solid == nullptr) {
      ++result.missing_solids;
      if (reports++ < 20) {
        std::cout << "MCGEOBRIDGE_POINT_MISSING solid=" << solid_name
                  << " cell=" << cell_id << "\n";
      }
      continue;
    }
    const bool inside = solid->Inside(G4ThreeVector(x * cm, y * cm, z * cm)) != kOutside;
    if (inside != (expected != 0)) {
      ++result.mismatches;
      if (reports++ < 20) {
        std::cout << "MCGEOBRIDGE_POINT_MISMATCH solid=" << solid_name
                  << " cell=" << cell_id << " strategy=" << strategy
                  << " point_cm=" << x << "," << y << "," << z
                  << " expected=" << expected << " geant4=" << inside << "\n";
      }
    }
  }
  return result;
}

NavigationResult CheckNavigationPoints(const std::string& path,
                                       G4VPhysicalVolume* world) {
  NavigationResult result;
  if (path.empty()) return result;
  std::ifstream input(path);
  if (!input) {
    std::cerr << "MCGEOBRIDGE_ERROR navigation_file_unreadable path=" << path << "\n";
    result.unresolved = 1;
    return result;
  }
  G4Navigator navigator;
  navigator.SetWorldVolume(world);
  std::string line;
  std::getline(input, line);  // header: label x_cm y_cm z_cm expected_logical_substring
  while (std::getline(input, line)) {
    if (line.empty()) continue;
    std::istringstream fields(line);
    std::string label;
    std::string expected;
    double x = 0.0;
    double y = 0.0;
    double z = 0.0;
    if (!(fields >> label >> x >> y >> z)) continue;
    fields >> expected;
    ++result.queries;
    auto* physical = navigator.LocateGlobalPointAndSetup(
        G4ThreeVector(x * cm, y * cm, z * cm), nullptr, false);
    if (physical == nullptr) {
      ++result.unresolved;
      std::cout << "MCGEOBRIDGE_NAVIGATION label=" << label
                << " status=unresolved\n";
      continue;
    }
    const std::string logical = physical->GetLogicalVolume()->GetName();
    const bool matches = expected.empty() || expected == "-" ||
                         logical.find(expected) != std::string::npos;
    if (!matches) ++result.mismatches;
    std::cout << "MCGEOBRIDGE_NAVIGATION label=" << label
              << " logical=" << logical
              << " expected=" << (expected.empty() ? "-" : expected)
              << " match=" << (matches ? 1 : 0) << "\n";
  }
  return result;
}

InteriorOverlapResult CheckInteriorOverlaps(
    G4VPhysicalVolume* world, int resolution, double overlap_tolerance) {
  std::vector<PlacedSolid> placed;
  auto* world_logical = world->GetLogicalVolume();
  placed.reserve(world_logical->GetNoDaughters());
  for (int index = 0; index < world_logical->GetNoDaughters(); ++index) {
    auto* physical = world_logical->GetDaughter(index);
    auto* solid = physical->GetLogicalVolume()->GetSolid();
    G4ThreeVector local_min;
    G4ThreeVector local_max;
    solid->BoundingLimits(local_min, local_max);
    G4AffineTransform transform(physical->GetRotation(), physical->GetTranslation());
    G4ThreeVector global_min(
        std::numeric_limits<double>::infinity(),
        std::numeric_limits<double>::infinity(),
        std::numeric_limits<double>::infinity());
    G4ThreeVector global_max(
        -std::numeric_limits<double>::infinity(),
        -std::numeric_limits<double>::infinity(),
        -std::numeric_limits<double>::infinity());
    for (int mask = 0; mask < 8; ++mask) {
      G4ThreeVector corner(
          (mask & 1) ? local_max.x() : local_min.x(),
          (mask & 2) ? local_max.y() : local_min.y(),
          (mask & 4) ? local_max.z() : local_min.z());
      const auto point = transform.TransformPoint(corner);
      global_min.setX(std::min(global_min.x(), point.x()));
      global_min.setY(std::min(global_min.y(), point.y()));
      global_min.setZ(std::min(global_min.z(), point.z()));
      global_max.setX(std::max(global_max.x(), point.x()));
      global_max.setY(std::max(global_max.y(), point.y()));
      global_max.setZ(std::max(global_max.z(), point.z()));
    }
    placed.push_back({physical, solid, transform, local_min, local_max, global_min, global_max});
  }

  // Sweep along X to avoid testing every sampled point against every volume.
  std::vector<std::vector<int>> candidates(placed.size());
  std::vector<int> order(placed.size());
  for (std::size_t i = 0; i < order.size(); ++i) order[i] = static_cast<int>(i);
  std::sort(order.begin(), order.end(), [&](int a, int b) {
    return placed[a].global_min.x() < placed[b].global_min.x();
  });
  for (std::size_t oi = 0; oi < order.size(); ++oi) {
    const int i = order[oi];
    for (std::size_t oj = oi + 1; oj < order.size(); ++oj) {
      const int j = order[oj];
      if (placed[j].global_min.x() >= placed[i].global_max.x()) break;
      if (placed[j].global_min.y() >= placed[i].global_max.y() ||
          placed[j].global_max.y() <= placed[i].global_min.y() ||
          placed[j].global_min.z() >= placed[i].global_max.z() ||
          placed[j].global_max.z() <= placed[i].global_min.z()) {
        continue;
      }
      candidates[i].push_back(j);
      candidates[j].push_back(i);
    }
  }

  std::mt19937_64 rng(0x4d4347454f425249ULL);
  std::set<std::pair<int, int>> overlap_pairs;
  std::set<std::pair<int, int>> tolerance_suppressed_pairs;
  std::set<int> overlap_volume_indices;
  InteriorOverlapResult result;
  int sampling_warning_reports = 0;
  const int target = std::max(1, resolution);
  const int attempt_factor = placed.size() <= 500 ? 200 : (placed.size() <= 2000 ? 50 : 5);
  const int max_attempts = std::max(200, target * attempt_factor);
  for (std::size_t i = 0; i < placed.size(); ++i) {
    const auto& item = placed[i];
    if (!std::isfinite(item.local_min.x()) || !std::isfinite(item.local_max.x()) ||
        !std::isfinite(item.local_min.y()) || !std::isfinite(item.local_max.y()) ||
        !std::isfinite(item.local_min.z()) || !std::isfinite(item.local_max.z())) {
      ++result.sampling_failed_volumes;
      continue;
    }
    std::uniform_real_distribution<double> xdist(item.local_min.x(), item.local_max.x());
    std::uniform_real_distribution<double> ydist(item.local_min.y(), item.local_max.y());
    std::uniform_real_distribution<double> zdist(item.local_min.z(), item.local_max.z());
    int accepted = 0;
    for (int attempt = 0; attempt < max_attempts && accepted < target; ++attempt) {
      const G4ThreeVector local(xdist(rng), ydist(rng), zdist(rng));
      if (item.solid->Inside(local) != kInside) continue;
      ++accepted;
      ++result.accepted_points;
      const G4ThreeVector global = item.transform.TransformPoint(local);
      for (const int j : candidates[i]) {
        const auto& sibling = placed[j];
        if (global.x() <= sibling.global_min.x() || global.x() >= sibling.global_max.x() ||
            global.y() <= sibling.global_min.y() || global.y() >= sibling.global_max.y() ||
            global.z() <= sibling.global_min.z() || global.z() >= sibling.global_max.z()) {
          continue;
        }
        const G4ThreeVector sibling_local = sibling.transform.InverseTransformPoint(global);
        if (sibling.solid->Inside(sibling_local) == kInside) {
          const auto pair = std::minmax(static_cast<int>(i), j);
          const double penetration = std::min(
              item.solid->DistanceToOut(local),
              sibling.solid->DistanceToOut(sibling_local));
          if (penetration <= overlap_tolerance) {
            tolerance_suppressed_pairs.insert(pair);
            continue;
          }
          if (overlap_pairs.insert(pair).second && overlap_pairs.size() <= 20) {
            std::cout << "MCGEOBRIDGE_OVERLAP_EVENT interior overlap between "
                      << item.physical->GetName() << " and "
                      << sibling.physical->GetName() << " at " << global
                      << " penetration_mm=" << penetration << "\n";
          }
          overlap_volume_indices.insert(static_cast<int>(i));
          overlap_volume_indices.insert(j);
        }
      }
    }
    if (accepted == 0) ++result.sampling_failed_volumes;
    if (accepted < target) {
      ++result.sampling_incomplete_volumes;
      if (sampling_warning_reports < 20) {
        std::cout << "MCGEOBRIDGE_SAMPLING_WARNING volume="
                  << item.physical->GetName() << " accepted=" << accepted
                  << " target=" << target << "\n";
        ++sampling_warning_reports;
      }
    }
  }
  result.overlap_pairs = static_cast<int>(overlap_pairs.size());
  result.overlap_volumes = static_cast<int>(overlap_volume_indices.size());
  result.tolerance_suppressed_pairs = static_cast<int>(tolerance_suppressed_pairs.size());
  return result;
}

int main(int argc, char** argv) {
  if (argc < 3) {
    std::cerr << "usage: mcnp2gdml_g4check FILE.gdml gdml.xsd [overlap_resolution] [surface|interior] [overlap_tolerance_mm] [point_queries.tsv] [navigation_points.tsv]\n";
    return 2;
  }

  const std::string gdml_path = argv[1];
  const std::string schema_path = argv[2];
  const int overlap_resolution = argc >= 4 ? std::atoi(argv[3]) : 0;
  const std::string overlap_method = argc >= 5 ? argv[4] : "surface";
  const double overlap_tolerance = argc >= 6 ? std::atof(argv[5]) * mm : 0.02 * mm;
  const std::string point_query_path = argc >= 7 ? argv[6] : "";
  const std::string navigation_query_path = argc >= 8 ? argv[7] : "";

  G4GDMLParser parser;
  parser.SetStripFlag(false);
  parser.SetImportSchema(schema_path);
  parser.Read(gdml_path, true);
  auto* world = parser.GetWorldVolume();
  if (world == nullptr) {
    std::cerr << "MCGEOBRIDGE_ERROR missing_world\n";
    return 3;
  }

  G4GeometryManager::GetInstance()->CloseGeometry();
  int check_failed_volumes = 0;
  int overlap_volumes = 0;
  int invalid_surface_volumes = 0;
  int interior_sampling_failed_volumes = 0;
  int interior_sampling_incomplete_volumes = 0;
  long long interior_accepted_points = 0;
  int tolerance_suppressed_pairs = 0;
  OverlapExceptionHandler exception_handler;
  if (overlap_resolution > 0 && overlap_method == "interior") {
    const auto result = CheckInteriorOverlaps(world, overlap_resolution, overlap_tolerance);
    overlap_volumes = result.overlap_volumes;
    interior_sampling_failed_volumes = result.sampling_failed_volumes;
    interior_sampling_incomplete_volumes = result.sampling_incomplete_volumes;
    interior_accepted_points = result.accepted_points;
    tolerance_suppressed_pairs = result.tolerance_suppressed_pairs;
    exception_handler.overlap_events = result.overlap_pairs;
  } else if (overlap_resolution > 0) {
    for (auto* physical : *G4PhysicalVolumeStore::GetInstance()) {
      if (physical == world) continue;
      const int overlap_events_before = exception_handler.overlap_events;
      const int invalid_events_before = exception_handler.invalid_surface_events;
      if (physical->CheckOverlaps(overlap_resolution, 0.0, false, 1)) {
        ++check_failed_volumes;
      }
      if (exception_handler.overlap_events > overlap_events_before) ++overlap_volumes;
      if (exception_handler.invalid_surface_events > invalid_events_before) {
        ++invalid_surface_volumes;
      }
    }
  }
  const auto point_result = CheckPointClassifications(point_query_path);
  const auto navigation_result = CheckNavigationPoints(navigation_query_path, world);

  for (const auto& description : exception_handler.overlap_descriptions) {
    std::cout << "MCGEOBRIDGE_OVERLAP_EVENT " << description << "\n";
  }

  std::cout << "MCGEOBRIDGE_RESULT"
            << " world=1"
            << " physical_volumes=" << G4PhysicalVolumeStore::GetInstance()->size()
            << " logical_volumes=" << G4LogicalVolumeStore::GetInstance()->size()
            << " solids=" << G4SolidStore::GetInstance()->size()
            << " materials=" << G4Material::GetNumberOfMaterials()
            << " overlap_checked=" << (overlap_resolution > 0 ? 1 : 0)
            << " interior_method=" << (overlap_method == "interior" ? 1 : 0)
            << " overlap_tolerance_um=" << static_cast<int>(overlap_tolerance / micrometer)
            << " check_failed_volumes=" << check_failed_volumes
            << " overlap_volumes=" << overlap_volumes
            << " overlap_events=" << exception_handler.overlap_events
            << " invalid_surface_volumes=" << invalid_surface_volumes
            << " invalid_surface_events=" << exception_handler.invalid_surface_events
            << " interior_sampling_failed_volumes=" << interior_sampling_failed_volumes
            << " interior_sampling_incomplete_volumes=" << interior_sampling_incomplete_volumes
            << " interior_accepted_points=" << interior_accepted_points
            << " tolerance_suppressed_pairs=" << tolerance_suppressed_pairs
            << " point_queries=" << point_result.queries
            << " point_mismatches=" << point_result.mismatches
            << " point_missing_solids=" << point_result.missing_solids
            << " navigation_queries=" << navigation_result.queries
            << " navigation_mismatches=" << navigation_result.mismatches
            << " navigation_unresolved=" << navigation_result.unresolved
            << " other_warning_events=" << exception_handler.other_warning_events << "\n";
  G4GeometryManager::GetInstance()->OpenGeometry();
  if (overlap_volumes > 0) return 4;
  if (invalid_surface_volumes > 0) return 5;
  if (interior_sampling_failed_volumes > 0) return 6;
  if (point_result.mismatches > 0 || point_result.missing_solids > 0 ||
      navigation_result.mismatches > 0 || navigation_result.unresolved > 0) return 7;
  return 0;
}
