#include "G4Colour.hh"
#include "G4Box.hh"
#include "G4GDMLParser.hh"
#include "G4LogicalVolume.hh"
#include "G4LogicalVolumeStore.hh"
#include "G4RotationMatrix.hh"
#include "G4PhysListFactory.hh"
#include "G4RayTracer.hh"
#include "G4RunManagerFactory.hh"
#include "G4String.hh"
#include "G4SubtractionSolid.hh"
#include "G4SystemOfUnits.hh"
#include "G4ThreeVector.hh"
#include "G4UImanager.hh"
#include "G4VUserDetectorConstruction.hh"
#include "G4VisAttributes.hh"
#include "G4VisManager.hh"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <iostream>
#include <limits>
#include <memory>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

class Detector final : public G4VUserDetectorConstruction {
 public:
  Detector(std::string gdml, std::set<std::string> hidden_volumes,
           std::vector<std::string> hidden_prefixes, bool cutaway_quarter,
           bool show_air, bool colour_by_volume)
      : gdml_(std::move(gdml)),
        hidden_volumes_(std::move(hidden_volumes)),
        hidden_prefixes_(std::move(hidden_prefixes)),
        cutaway_quarter_(cutaway_quarter),
        show_air_(show_air),
        colour_by_volume_(colour_by_volume) {}

  G4VPhysicalVolume* Construct() override {
    parser_.Read(gdml_, false);
    world_ = parser_.GetWorldVolume();
    if (!world_) throw std::runtime_error("GDML has no world volume");
    ComputeSceneBounds();
    if (cutaway_quarter_) ApplyGeometryCutaway();
    ExpandWorld();
    ApplyColours();
    return world_;
  }

  G4VPhysicalVolume* World() const { return world_; }
  const G4ThreeVector& SceneMinimum() const { return scene_minimum_; }
  const G4ThreeVector& SceneMaximum() const { return scene_maximum_; }

 private:
  bool IsHidden(const G4LogicalVolume* logical) const {
    if (logical == world_->GetLogicalVolume()) return true;
    const std::string material = logical->GetMaterial()->GetName();
    const bool air = material == "Air" || material.find("AIR") != std::string::npos;
    if (!show_air_ && air) return true;
    const std::string logical_name = logical->GetName();
    const bool hidden_by_prefix = std::any_of(
        hidden_prefixes_.begin(), hidden_prefixes_.end(),
        [&logical_name](const std::string& prefix) {
          return logical_name.rfind(prefix, 0) == 0;
        });
    return hidden_volumes_.count(logical_name) != 0 || hidden_by_prefix;
  }

  void IncludePoint(const G4ThreeVector& point) {
    scene_minimum_.setX(std::min(scene_minimum_.x(), point.x()));
    scene_minimum_.setY(std::min(scene_minimum_.y(), point.y()));
    scene_minimum_.setZ(std::min(scene_minimum_.z(), point.z()));
    scene_maximum_.setX(std::max(scene_maximum_.x(), point.x()));
    scene_maximum_.setY(std::max(scene_maximum_.y(), point.y()));
    scene_maximum_.setZ(std::max(scene_maximum_.z(), point.z()));
  }

  void AccumulateDaughters(G4LogicalVolume* mother,
                           const G4RotationMatrix& parent_rotation,
                           const G4ThreeVector& parent_translation) {
    for (int index = 0; index < mother->GetNoDaughters(); ++index) {
      auto* physical = mother->GetDaughter(index);
      const G4RotationMatrix rotation =
          parent_rotation * physical->GetObjectRotationValue();
      const G4ThreeVector translation =
          parent_rotation * physical->GetObjectTranslation() + parent_translation;
      if (!IsHidden(physical->GetLogicalVolume())) {
        G4ThreeVector local_minimum, local_maximum;
        physical->GetLogicalVolume()->GetSolid()->BoundingLimits(local_minimum, local_maximum);
        for (int x = 0; x < 2; ++x) {
          for (int y = 0; y < 2; ++y) {
            for (int z = 0; z < 2; ++z) {
              const G4ThreeVector corner(
                  x ? local_maximum.x() : local_minimum.x(),
                  y ? local_maximum.y() : local_minimum.y(),
                  z ? local_maximum.z() : local_minimum.z());
              IncludePoint(rotation * corner + translation);
            }
          }
        }
      }
      AccumulateDaughters(physical->GetLogicalVolume(), rotation, translation);
    }
  }

  void ComputeSceneBounds() {
    const double infinity = std::numeric_limits<double>::infinity();
    scene_minimum_ = G4ThreeVector(infinity, infinity, infinity);
    scene_maximum_ = G4ThreeVector(-infinity, -infinity, -infinity);
    AccumulateDaughters(world_->GetLogicalVolume(), G4RotationMatrix(), G4ThreeVector());
    if (!std::isfinite(scene_minimum_.x())) {
      world_->GetLogicalVolume()->GetSolid()->BoundingLimits(scene_minimum_, scene_maximum_);
    }
  }

  void ApplyGeometryCutaway() {
    const double extent = 2.0 * std::max({
        std::abs(scene_minimum_.x()), std::abs(scene_maximum_.x()),
        std::abs(scene_minimum_.y()), std::abs(scene_maximum_.y()),
        std::abs(scene_minimum_.z()), std::abs(scene_maximum_.z()), 1.0 * mm});
    // This box occupies x>=0 and y<=0 in each solid's local coordinates.  It
    // is subtracted from every displayed solid, producing two genuine section
    // faces that the RayTracer can follow.  The GDML on disk is not modified.
    auto* quadrant = new G4Box("MCGeoBridgeRenderCutaway", extent, extent, extent);
    const G4ThreeVector offset(extent, -extent, 0.0);
    for (auto* logical : *G4LogicalVolumeStore::GetInstance()) {
      if (logical == world_->GetLogicalVolume()) continue;
      auto* original = logical->GetSolid();
      logical->SetSolid(new G4SubtractionSolid(
          "MCGeoBridgeRenderCut_" + logical->GetName(), original, quadrant, nullptr, offset));
    }
  }

  void ExpandWorld() {
    const double extent = 4.0 * std::max({
        std::abs(scene_minimum_.x()), std::abs(scene_maximum_.x()),
        std::abs(scene_minimum_.y()), std::abs(scene_maximum_.y()),
        std::abs(scene_minimum_.z()), std::abs(scene_maximum_.z()), 1.0 * mm});
    world_->GetLogicalVolume()->SetSolid(
        new G4Box("MCGeoBridgeRenderWorld", extent, extent, extent));
  }

  static G4Colour ColourFor(const std::string& value, double alpha) {
    std::uint32_t hash = 2166136261u;
    for (const unsigned char c : value) hash = (hash ^ c) * 16777619u;
    const double hue = (hash % 360u) / 360.0;
    const double x = hue * 6.0;
    const int sector = static_cast<int>(std::floor(x)) % 6;
    const double f = x - std::floor(x);
    const double p = 0.25;
    const double q = 0.85 - 0.60 * f;
    const double t = 0.25 + 0.60 * f;
    double r = 0.85, g = t, b = p;
    if (sector == 1) { r = q; g = 0.85; b = p; }
    if (sector == 2) { r = p; g = 0.85; b = t; }
    if (sector == 3) { r = p; g = q; b = 0.85; }
    if (sector == 4) { r = t; g = p; b = 0.85; }
    if (sector == 5) { r = 0.85; g = p; b = q; }
    return {r, g, b, alpha};
  }

  void ApplyColours() {
    for (auto* logical : *G4LogicalVolumeStore::GetInstance()) {
      auto attributes = std::make_unique<G4VisAttributes>();
      if (logical == world_->GetLogicalVolume()) {
        attributes->SetVisibility(false);
      } else {
        const std::string material = logical->GetMaterial()->GetName();
        const std::string logical_name = logical->GetName();
        attributes->SetVisibility(!IsHidden(logical));
        attributes->SetForceSolid(true);
        // Material-consistent colours make repeated fuel-pin patterns legible;
        // per-instance colours visually obscure the very repetition being shown.
        attributes->SetColour(ColourFor(colour_by_volume_ ? logical_name : material, 0.78));
        std::cout << "MCGEOBRIDGE_RENDER_VOLUME name=" << logical->GetName()
                  << " material=" << material
                  << " visible=" << (attributes->IsVisible() ? "true" : "false")
                  << std::endl;
      }
      logical->SetVisAttributes(attributes.get());
      attributes_.push_back(std::move(attributes));
    }
  }

  std::string gdml_;
  std::set<std::string> hidden_volumes_;
  std::vector<std::string> hidden_prefixes_;
  bool cutaway_quarter_ = false;
  bool show_air_ = false;
  bool colour_by_volume_ = false;
  G4ThreeVector scene_minimum_;
  G4ThreeVector scene_maximum_;
  G4GDMLParser parser_;
  G4VPhysicalVolume* world_ = nullptr;
  std::vector<std::unique_ptr<G4VisAttributes>> attributes_;
};

class RayTracerVisManager final : public G4VisManager {
 protected:
  void RegisterGraphicsSystems() override { RegisterGraphicsSystem(new G4RayTracer); }
};

void Apply(G4UImanager* ui, const std::string& command) {
  const int status = ui->ApplyCommand(command);
  if (status != 0) throw std::runtime_error("Geant4 command failed: " + command);
}

}  // namespace

struct Options {
  std::string gdml;
  std::filesystem::path output;
  int width = 1200;
  int height = 900;
  bool cutaway_quarter = false;
  bool show_air = false;
  bool top_view = false;
  bool colour_by_volume = false;
  double zoom = 1.0;
  std::set<std::string> hidden_volumes;
  std::vector<std::string> hidden_prefixes;
};

Options ParseOptions(int argc, char** argv) {
  if (argc < 3) {
    throw std::runtime_error(
        "usage: mcgeobridge_gdml_render MODEL.gdml OUTPUT.jpeg [width height] "
        "[--cutaway-quarter] [--show-air] [--top-view] [--colour-by-volume] "
        "[--zoom FACTOR] [--hide VOLUME] [--hide-prefix PREFIX]");
  }
  Options options;
  options.gdml = argv[1];
  options.output = std::filesystem::absolute(argv[2]);
  int index = 3;
  if (index < argc && argv[index][0] != '-') options.width = std::stoi(argv[index++]);
  if (index < argc && argv[index][0] != '-') options.height = std::stoi(argv[index++]);
  while (index < argc) {
    const std::string argument = argv[index++];
    if (argument == "--cutaway-quarter") {
      options.cutaway_quarter = true;
    } else if (argument == "--show-air") {
      options.show_air = true;
    } else if (argument == "--top-view") {
      options.top_view = true;
    } else if (argument == "--colour-by-volume") {
      options.colour_by_volume = true;
    } else if (argument == "--zoom") {
      if (index == argc) throw std::runtime_error("--zoom requires a positive factor");
      options.zoom = std::stod(argv[index++]);
    } else if (argument == "--hide") {
      if (index == argc) throw std::runtime_error("--hide requires a logical-volume name");
      options.hidden_volumes.insert(argv[index++]);
    } else if (argument == "--hide-prefix") {
      if (index == argc) throw std::runtime_error("--hide-prefix requires a prefix");
      options.hidden_prefixes.push_back(argv[index++]);
    } else {
      throw std::runtime_error("unknown option: " + argument);
    }
  }
  if (options.width <= 0 || options.height <= 0 || options.zoom <= 0.0) {
    throw std::runtime_error("image dimensions and zoom factor must be positive");
  }
  return options;
}

int main(int argc, char** argv) {
  try {
    const Options options = ParseOptions(argc, argv);

    auto* run_manager = G4RunManagerFactory::CreateRunManager(G4RunManagerType::SerialOnly);
    auto* detector = new Detector(
        options.gdml, options.hidden_volumes, options.hidden_prefixes,
        options.cutaway_quarter, options.show_air, options.colour_by_volume);
    run_manager->SetUserInitialization(detector);
    G4PhysListFactory factory;
    run_manager->SetUserInitialization(factory.GetReferencePhysList("FTFP_BERT"));
    run_manager->Initialize();

    const G4ThreeVector minimum = detector->SceneMinimum();
    const G4ThreeVector maximum = detector->SceneMaximum();
    const G4ThreeVector target = 0.5 * (minimum + maximum);
    const G4ThreeVector half = 0.5 * (maximum - minimum);
    // Geant4 tracks, including RayTracer rays, must start inside the world.
    // Stay close to an isometric corner while retaining a small safety margin.
    const double radius = options.top_view
        ? std::max({half.x(), half.y(), 1.0 * mm})
        : std::max({half.x(), half.y(), half.z(), 1.0 * mm});
    const G4ThreeVector eye_offset = options.top_view
        ? G4ThreeVector(0.0, 0.0, 2.5 * radius)
        : G4ThreeVector(2.0 * radius, -2.0 * radius, 1.5 * radius);
    const G4ThreeVector eye = target + eye_offset / options.zoom;

    auto* vis_manager = new RayTracerVisManager;
    vis_manager->Initialize();
    auto* ui = G4UImanager::GetUIpointer();
    Apply(ui, "/vis/verbose confirmations");
    Apply(ui, "/vis/scene/create");
    Apply(ui, "/vis/sceneHandler/create RayTracer");
    Apply(ui, "/vis/viewer/create");
    Apply(ui, "/vis/viewer/select viewer-0");
    Apply(ui, "/vis/scene/add/volume");
    Apply(ui, "/vis/viewer/rebuild");
    Apply(ui, "/vis/rayTracer/column " + std::to_string(options.width));
    Apply(ui, "/vis/rayTracer/row " + std::to_string(options.height));
    Apply(ui, "/vis/viewer/set/projection p");
    Apply(ui, "/vis/rayTracer/target " + std::to_string(target.x() / mm) + " " +
                  std::to_string(target.y() / mm) + " " + std::to_string(target.z() / mm) + " mm");
    Apply(ui, "/vis/rayTracer/eyePosition " + std::to_string(eye.x() / mm) + " " +
                  std::to_string(eye.y() / mm) + " " + std::to_string(eye.z() / mm) + " mm");
    Apply(ui, "/vis/rayTracer/lightDirection -1 1 -1");
    Apply(ui, "/vis/rayTracer/span 38 deg");
    Apply(ui, "/vis/viewer/set/background 1 1 1");
    Apply(ui, "/vis/viewer/rebuild");
    Apply(ui, "/vis/rayTracer/trace " + options.output.string());

    delete vis_manager;
    delete run_manager;
    if (!std::filesystem::exists(options.output)) {
      throw std::runtime_error("renderer did not create output image");
    }
    std::cout << "MCGEOBRIDGE_RENDER_RESULT status=complete output=" << options.output.string()
              << " width=" << options.width << " height=" << options.height
              << " cutaway_quarter=" << (options.cutaway_quarter ? "true" : "false")
              << " top_view=" << (options.top_view ? "true" : "false")
              << " zoom=" << options.zoom
              << std::endl;
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "MCGEOBRIDGE_RENDER_ERROR " << error.what() << std::endl;
    return 1;
  }
}
