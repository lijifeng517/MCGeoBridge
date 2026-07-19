#include "G4Box.hh"
#include "G4Event.hh"
#include "G4GDMLParser.hh"
#include "G4LogicalVolume.hh"
#include "G4LogicalVolumeStore.hh"
#include "G4ParticleGun.hh"
#include "G4ParticleTable.hh"
#include "G4PhysListFactory.hh"
#include "G4Run.hh"
#include "G4RunManagerFactory.hh"
#include "G4Step.hh"
#include "G4SystemOfUnits.hh"
#include "G4ThreeVector.hh"
#include "G4TransportationManager.hh"
#include "G4UserEventAction.hh"
#include "G4UserRunAction.hh"
#include "G4UserSteppingAction.hh"
#include "G4VUserActionInitialization.hh"
#include "G4VUserDetectorConstruction.hh"
#include "G4VUserPrimaryGeneratorAction.hh"
#include "G4VModularPhysicsList.hh"
#include "Randomize.hh"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <memory>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace {

struct Config {
  std::string gdml;
  std::string output;
  std::string physics = "Shielding";
  long events = 1000;
  long seed = 1234567;
  double energy_mev = 2.0;
  G4ThreeVector position_mm{0., 0., 0.};
  G4ThreeVector direction{0., 0., 1.};
  bool compute_volumes = false;
};

double ParseDouble(const char* text, const std::string& label) {
  try {
    std::size_t consumed = 0;
    const double value = std::stod(text, &consumed);
    if (consumed != std::string(text).size() || !std::isfinite(value)) {
      throw std::invalid_argument("not finite");
    }
    return value;
  } catch (...) {
    throw std::runtime_error("invalid " + label + ": " + text);
  }
}

long ParseLong(const char* text, const std::string& label) {
  try {
    std::size_t consumed = 0;
    const long value = std::stol(text, &consumed);
    if (consumed != std::string(text).size()) throw std::invalid_argument("trailing");
    return value;
  } catch (...) {
    throw std::runtime_error("invalid " + label + ": " + text);
  }
}

Config ParseArgs(int argc, char** argv) {
  if (argc < 3) {
    throw std::runtime_error(
        "usage: mcgeobridge_transport MODEL.gdml RESULT.json [options]\n"
        "  --events N --seed N --physics NAME --energy-mev E\n"
        "  --position-mm X Y Z --direction DX DY DZ --compute-volumes");
  }
  Config cfg;
  cfg.gdml = argv[1];
  cfg.output = argv[2];
  for (int i = 3; i < argc; ++i) {
    const std::string arg = argv[i];
    auto need = [&](int count) {
      if (i + count >= argc) throw std::runtime_error("missing value after " + arg);
    };
    if (arg == "--events") {
      need(1); cfg.events = ParseLong(argv[++i], "event count");
    } else if (arg == "--seed") {
      need(1); cfg.seed = ParseLong(argv[++i], "seed");
    } else if (arg == "--physics") {
      need(1); cfg.physics = argv[++i];
    } else if (arg == "--energy-mev") {
      need(1); cfg.energy_mev = ParseDouble(argv[++i], "energy");
    } else if (arg == "--position-mm") {
      need(3);
      const double x = ParseDouble(argv[++i], "source x");
      const double y = ParseDouble(argv[++i], "source y");
      const double z = ParseDouble(argv[++i], "source z");
      cfg.position_mm = {x, y, z};
    } else if (arg == "--direction") {
      need(3);
      const double x = ParseDouble(argv[++i], "direction x");
      const double y = ParseDouble(argv[++i], "direction y");
      const double z = ParseDouble(argv[++i], "direction z");
      cfg.direction = {x, y, z};
    } else if (arg == "--compute-volumes") {
      cfg.compute_volumes = true;
    } else {
      throw std::runtime_error("unknown option: " + arg);
    }
  }
  if (cfg.events <= 0) throw std::runtime_error("--events must be positive");
  if (cfg.energy_mev <= 0.) throw std::runtime_error("--energy-mev must be positive");
  if (cfg.direction.mag2() == 0.) throw std::runtime_error("source direction cannot be zero");
  cfg.direction = cfg.direction.unit();
  return cfg;
}

std::string JsonEscape(const std::string& value) {
  std::ostringstream out;
  for (const unsigned char c : value) {
    switch (c) {
      case '\\': out << "\\\\"; break;
      case '"': out << "\\\""; break;
      case '\n': out << "\\n"; break;
      case '\r': out << "\\r"; break;
      case '\t': out << "\\t"; break;
      default:
        if (c < 0x20) out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << int(c);
        else out << c;
    }
  }
  return out.str();
}

struct EventScore {
  double neutron_track_mm = 0.;
  double energy_deposit_mev = 0.;
  double leakage_energy_mev = 0.;
  std::uint64_t captures = 0;
  std::uint64_t fissions = 0;
  std::uint64_t leakage_neutrons = 0;
};

struct Accumulator {
  double sum = 0.;
  double sum_sq = 0.;
  void Add(double value) { sum += value; sum_sq += value * value; }
  double Mean(long n) const { return n > 0 ? sum / n : 0.; }
  double StandardError(long n) const {
    if (n < 2) return 0.;
    const double variance = std::max(0.0, (sum_sq - sum * sum / n) / (n - 1));
    return std::sqrt(variance / n);
  }
};

struct VolumeScore {
  Accumulator neutron_track_mm;
  Accumulator energy_deposit_mev;
  Accumulator captures;
  Accumulator fissions;
};

std::optional<int> CellIdFromVolume(const std::string& name) {
  if (name.rfind("Vol_", 0) != 0) return std::nullopt;
  const std::size_t begin = 4;
  const std::size_t end = name.find('_', begin);
  if (end == std::string::npos) return std::nullopt;
  try {
    return std::stoi(name.substr(begin, end - begin));
  } catch (...) {
    return std::nullopt;
  }
}

class ScoreBook {
 public:
  void BeginEvent() { current_.clear(); cell_current_.clear(); leakage_ = {}; }

  EventScore& ForVolume(const std::string& name) { return current_[name]; }
  EventScore& ForCell(int cell_id) { return cell_current_[cell_id]; }
  EventScore& Leakage() { return leakage_; }

  void EndEvent() {
    ++events_;
    for (const auto& entry : current_) {
      auto& total = volumes_[entry.first];
      total.neutron_track_mm.Add(entry.second.neutron_track_mm);
      total.energy_deposit_mev.Add(entry.second.energy_deposit_mev);
      total.captures.Add(static_cast<double>(entry.second.captures));
      total.fissions.Add(static_cast<double>(entry.second.fissions));
    }
    for (const auto& entry : cell_current_) {
      auto& total = cells_[entry.first];
      total.neutron_track_mm.Add(entry.second.neutron_track_mm);
      total.energy_deposit_mev.Add(entry.second.energy_deposit_mev);
      total.captures.Add(static_cast<double>(entry.second.captures));
      total.fissions.Add(static_cast<double>(entry.second.fissions));
    }
    leakage_energy_.Add(leakage_.leakage_energy_mev);
    leakage_count_.Add(static_cast<double>(leakage_.leakage_neutrons));
  }

  void Write(const Config& cfg) const {
    std::ofstream out(cfg.output);
    if (!out) throw std::runtime_error("cannot write result: " + cfg.output);
    out << std::setprecision(12);
    out << "{\n  \"schema_version\": 1,\n  \"status\": \"complete\",\n";
    out << "  \"model\": \"" << JsonEscape(cfg.gdml) << "\",\n";
    out << "  \"physics_list\": \"" << JsonEscape(cfg.physics) << "\",\n";
    out << "  \"events\": " << events_ << ",\n  \"seed\": " << cfg.seed << ",\n";
    out << "  \"source\": {\"particle\": \"neutron\", \"energy_mev\": " << cfg.energy_mev
        << ", \"position_mm\": [" << cfg.position_mm.x() << ", " << cfg.position_mm.y() << ", "
        << cfg.position_mm.z() << "], \"direction\": [" << cfg.direction.x() << ", "
        << cfg.direction.y() << ", " << cfg.direction.z() << "], \"initial_volume\": \""
        << JsonEscape(source_volume_) << "\"},\n";
    out << "  \"leakage\": {\"neutrons_per_source\": " << leakage_count_.Mean(events_)
        << ", \"neutrons_per_source_se\": " << leakage_count_.StandardError(events_)
        << ", \"energy_mev_per_source\": " << leakage_energy_.Mean(events_)
        << ", \"energy_mev_per_source_se\": " << leakage_energy_.StandardError(events_) << "},\n";
    out << "  \"volumes\": [\n";
    bool first = true;
    for (auto* logical : *G4LogicalVolumeStore::GetInstance()) {
      const auto found = volumes_.find(logical->GetName());
      if (found == volumes_.end()) continue;
      if (!first) out << ",\n";
      first = false;
      const auto& score = found->second;
      const double track_mean = score.neutron_track_mm.Mean(events_);
      const double track_se = score.neutron_track_mm.StandardError(events_);
      out << "    {\"name\": \"" << JsonEscape(logical->GetName()) << "\", \"material\": \""
          << JsonEscape(logical->GetMaterial()->GetName()) << "\"";
      if (cfg.compute_volumes) {
        const double volume_mm3 = logical->GetSolid()->GetCubicVolume() / mm3;
        out << ", \"volume_mm3\": " << volume_mm3
            << ", \"neutron_track_mm_per_source\": " << track_mean
            << ", \"neutron_track_mm_per_source_se\": " << track_se
            << ", \"track_length_flux_per_mm2\": " << (volume_mm3 > 0. ? track_mean / volume_mm3 : 0.)
            << ", \"track_length_flux_per_mm2_se\": " << (volume_mm3 > 0. ? track_se / volume_mm3 : 0.);
      } else {
        out << ", \"volume_mm3\": null"
            << ", \"neutron_track_mm_per_source\": " << track_mean
            << ", \"neutron_track_mm_per_source_se\": " << track_se
            << ", \"track_length_flux_per_mm2\": null, \"track_length_flux_per_mm2_se\": null";
      }
      out << ", \"energy_deposit_mev_per_source\": " << score.energy_deposit_mev.Mean(events_)
          << ", \"energy_deposit_mev_per_source_se\": " << score.energy_deposit_mev.StandardError(events_)
          << ", \"captures_per_source\": " << score.captures.Mean(events_)
          << ", \"captures_per_source_se\": " << score.captures.StandardError(events_)
          << ", \"fissions_per_source\": " << score.fissions.Mean(events_)
          << ", \"fissions_per_source_se\": " << score.fissions.StandardError(events_) << "}";
    }
    out << "\n  ],\n  \"cells\": [\n";
    first = true;
    for (const auto& entry : cells_) {
      if (!first) out << ",\n";
      first = false;
      const int cell_id = entry.first;
      const auto& score = entry.second;
      const double track_mean = score.neutron_track_mm.Mean(events_);
      const double track_se = score.neutron_track_mm.StandardError(events_);
      out << "    {\"cell_id\": " << cell_id
          << ", \"neutron_track_mm_per_source\": " << track_mean
          << ", \"neutron_track_mm_per_source_se\": " << track_se
          << ", \"energy_deposit_mev_per_source\": " << score.energy_deposit_mev.Mean(events_)
          << ", \"energy_deposit_mev_per_source_se\": " << score.energy_deposit_mev.StandardError(events_)
          << ", \"captures_per_source\": " << score.captures.Mean(events_)
          << ", \"captures_per_source_se\": " << score.captures.StandardError(events_)
          << ", \"fissions_per_source\": " << score.fissions.Mean(events_)
          << ", \"fissions_per_source_se\": " << score.fissions.StandardError(events_) << "}";
    }
    out << "\n  ]\n}\n";
  }

  void SetSourceVolume(const std::string& name) {
    if (source_volume_.empty()) source_volume_ = name;
  }

 private:
  long events_ = 0;
  std::map<std::string, EventScore> current_;
  std::map<int, EventScore> cell_current_;
  EventScore leakage_;
  std::map<std::string, VolumeScore> volumes_;
  std::map<int, VolumeScore> cells_;
  Accumulator leakage_energy_;
  Accumulator leakage_count_;
  std::string source_volume_;
};

class DetectorConstruction final : public G4VUserDetectorConstruction {
 public:
  explicit DetectorConstruction(std::string path) : path_(std::move(path)) {}
  G4VPhysicalVolume* Construct() override {
    parser_.Read(path_, false);
    auto* world = parser_.GetWorldVolume();
    if (!world) throw std::runtime_error("GDML has no world volume");
    return world;
  }
 private:
  std::string path_;
  G4GDMLParser parser_;
};

class PrimaryGenerator final : public G4VUserPrimaryGeneratorAction {
 public:
  explicit PrimaryGenerator(const Config& cfg) : gun_(1) {
    auto* neutron = G4ParticleTable::GetParticleTable()->FindParticle("neutron");
    if (!neutron) throw std::runtime_error("Geant4 neutron definition unavailable");
    gun_.SetParticleDefinition(neutron);
    gun_.SetParticleEnergy(cfg.energy_mev * MeV);
    gun_.SetParticlePosition(cfg.position_mm * mm);
    gun_.SetParticleMomentumDirection(cfg.direction);
  }
  void GeneratePrimaries(G4Event* event) override { gun_.GeneratePrimaryVertex(event); }
 private:
  G4ParticleGun gun_;
};

class EventAction final : public G4UserEventAction {
 public:
  explicit EventAction(std::shared_ptr<ScoreBook> scores) : scores_(std::move(scores)) {}
  void BeginOfEventAction(const G4Event*) override { scores_->BeginEvent(); }
  void EndOfEventAction(const G4Event*) override { scores_->EndEvent(); }
 private:
  std::shared_ptr<ScoreBook> scores_;
};

class SteppingAction final : public G4UserSteppingAction {
 public:
  explicit SteppingAction(std::shared_ptr<ScoreBook> scores) : scores_(std::move(scores)) {}
  void UserSteppingAction(const G4Step* step) override {
    const auto* track = step->GetTrack();
    const auto* pre_volume = step->GetPreStepPoint()->GetTouchableHandle()->GetVolume();
    if (pre_volume) {
      if (track->GetParentID() == 0 && track->GetCurrentStepNumber() == 1) {
        scores_->SetSourceVolume(pre_volume->GetLogicalVolume()->GetName());
      }
      const std::string volume_name = pre_volume->GetLogicalVolume()->GetName();
      auto& score = scores_->ForVolume(volume_name);
      EventScore* cell_score = nullptr;
      const auto cell_id = CellIdFromVolume(volume_name);
      if (cell_id) cell_score = &scores_->ForCell(*cell_id);
      if (track->GetDefinition()->GetParticleName() == "neutron") {
        score.neutron_track_mm += step->GetStepLength() / mm;
        if (cell_score) cell_score->neutron_track_mm += step->GetStepLength() / mm;
      }
      score.energy_deposit_mev += step->GetTotalEnergyDeposit() / MeV;
      if (cell_score) cell_score->energy_deposit_mev += step->GetTotalEnergyDeposit() / MeV;
      const auto* process = step->GetPostStepPoint()->GetProcessDefinedStep();
      if (process) {
        const std::string name = process->GetProcessName();
        if (name.find("Capture") != std::string::npos || name == "nCapture") {
          ++score.captures;
          if (cell_score) ++cell_score->captures;
        }
        if (name.find("Fission") != std::string::npos || name == "nFission") {
          ++score.fissions;
          if (cell_score) ++cell_score->fissions;
        }
      }
    }
    if (track->GetDefinition()->GetParticleName() == "neutron" &&
        step->GetPostStepPoint()->GetStepStatus() == fWorldBoundary) {
      auto& leakage = scores_->Leakage();
      ++leakage.leakage_neutrons;
      leakage.leakage_energy_mev += step->GetPostStepPoint()->GetKineticEnergy() / MeV;
    }
  }
 private:
  std::shared_ptr<ScoreBook> scores_;
};

class RunAction final : public G4UserRunAction {
 public:
  RunAction(std::shared_ptr<ScoreBook> scores, Config cfg)
      : scores_(std::move(scores)), cfg_(std::move(cfg)) {}
  void EndOfRunAction(const G4Run*) override { scores_->Write(cfg_); }
 private:
  std::shared_ptr<ScoreBook> scores_;
  Config cfg_;
};

class ActionInitialization final : public G4VUserActionInitialization {
 public:
  explicit ActionInitialization(Config cfg) : cfg_(std::move(cfg)), scores_(std::make_shared<ScoreBook>()) {}
  void Build() const override {
    SetUserAction(new PrimaryGenerator(cfg_));
    SetUserAction(new RunAction(scores_, cfg_));
    SetUserAction(new EventAction(scores_));
    SetUserAction(new SteppingAction(scores_));
  }
 private:
  Config cfg_;
  std::shared_ptr<ScoreBook> scores_;
};

}  // namespace

int main(int argc, char** argv) {
  try {
    const Config cfg = ParseArgs(argc, argv);
    G4Random::setTheSeed(cfg.seed);
    auto* run_manager = G4RunManagerFactory::CreateRunManager(G4RunManagerType::SerialOnly);
    run_manager->SetUserInitialization(new DetectorConstruction(cfg.gdml));
    G4PhysListFactory factory;
    auto* physics = factory.GetReferencePhysList(cfg.physics);
    if (!physics) throw std::runtime_error("unknown Geant4 physics list: " + cfg.physics);
    run_manager->SetUserInitialization(physics);
    run_manager->SetUserInitialization(new ActionInitialization(cfg));
    run_manager->Initialize();
    run_manager->BeamOn(cfg.events);
    delete run_manager;
    std::cout << "MCGEOBRIDGE_TRANSPORT_RESULT status=complete events=" << cfg.events
              << " output=" << cfg.output << std::endl;
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "MCGEOBRIDGE_TRANSPORT_ERROR " << error.what() << std::endl;
    return 1;
  }
}
