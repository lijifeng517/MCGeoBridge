#include "G4Event.hh"
#include "G4GDMLParser.hh"
#include "G4GeometryManager.hh"
#include "G4HadronicProcess.hh"
#include "G4Nucleus.hh"
#include "G4ParticleGun.hh"
#include "G4ParticleHPManager.hh"
#include "G4ParticleTable.hh"
#include "G4PhysListFactory.hh"
#include "G4RunManagerFactory.hh"
#include "G4Step.hh"
#include "G4SystemOfUnits.hh"
#include "G4ThreeVector.hh"
#include "G4Track.hh"
#include "G4TransportationManager.hh"
#include "G4UserStackingAction.hh"
#include "G4UserSteppingAction.hh"
#include "G4VProcess.hh"
#include "G4VUserActionInitialization.hh"
#include "G4VUserDetectorConstruction.hh"
#include "G4VUserPrimaryGeneratorAction.hh"
#include "Randomize.hh"

#include <algorithm>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <memory>
#include <numeric>
#include <sstream>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>

namespace {

struct Config {
  std::string gdml;
  std::string output;
  std::string physics = "Shielding";
  long population = 1000;
  long inactive = 20;
  long active = 100;
  long seed = 1234567;
  G4ThreeVector initial_position_mm{0., 0., 0.};
  std::vector<G4ThreeVector> initial_positions_mm;
  std::string source_points_path;
  bool locate_only = false;
  bool disable_hp_fission_fragments = false;
  double initial_energy_mev = 2.0;
  double source_bin_mm = 20.0;
};

struct SourceParticle {
  G4ThreeVector position;
  G4ThreeVector direction;
  double energy = 0.;
  double weight = 1.;
};

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

std::vector<G4ThreeVector> ReadSourcePoints(const std::string& path) {
  std::ifstream input(path);
  if (!input) throw std::runtime_error("cannot read source-point file: " + path);
  std::vector<G4ThreeVector> points;
  std::string line;
  while (std::getline(input, line)) {
    const auto comment = line.find('#');
    if (comment != std::string::npos) line.erase(comment);
    std::istringstream fields(line);
    double x = 0.0;
    double y = 0.0;
    double z = 0.0;
    if (!(fields >> x >> y >> z)) continue;
    points.emplace_back(x, y, z);
  }
  if (points.empty()) throw std::runtime_error("source-point file has no XYZ rows: " + path);
  return points;
}

Config ParseArgs(int argc, char** argv) {
  if (argc < 3) {
    throw std::runtime_error(
        "usage: mcgeobridge_criticality MODEL.gdml RESULT.json [options]\n"
        "  --population N --inactive N --active N --seed N --physics NAME\n"
        "  --position-mm X Y Z --source-points-mm FILE --locate-only --energy-mev E\n"
        "  --source-bin-mm W --disable-hp-fission-fragments");
  }
  Config cfg;
  cfg.gdml = argv[1];
  cfg.output = argv[2];
  for (int i = 3; i < argc; ++i) {
    const std::string arg = argv[i];
    auto need = [&](int count) {
      if (i + count >= argc) throw std::runtime_error("missing value after " + arg);
    };
    if (arg == "--population") {
      need(1); cfg.population = ParseLong(argv[++i], "population");
    } else if (arg == "--inactive") {
      need(1); cfg.inactive = ParseLong(argv[++i], "inactive cycles");
    } else if (arg == "--active") {
      need(1); cfg.active = ParseLong(argv[++i], "active cycles");
    } else if (arg == "--seed") {
      need(1); cfg.seed = ParseLong(argv[++i], "seed");
    } else if (arg == "--physics") {
      need(1); cfg.physics = argv[++i];
    } else if (arg == "--energy-mev") {
      need(1); cfg.initial_energy_mev = ParseDouble(argv[++i], "initial energy");
    } else if (arg == "--source-bin-mm") {
      need(1); cfg.source_bin_mm = ParseDouble(argv[++i], "source bin width");
    } else if (arg == "--position-mm") {
      need(3);
      cfg.initial_position_mm = {
          ParseDouble(argv[++i], "source x"), ParseDouble(argv[++i], "source y"),
          ParseDouble(argv[++i], "source z")};
    } else if (arg == "--source-points-mm") {
      need(1); cfg.source_points_path = argv[++i];
    } else if (arg == "--locate-only") {
      cfg.locate_only = true;
    } else if (arg == "--disable-hp-fission-fragments") {
      cfg.disable_hp_fission_fragments = true;
    } else {
      throw std::runtime_error("unknown option: " + arg);
    }
  }
  if (cfg.population <= 0 || cfg.inactive < 0 || cfg.active <= 1 ||
      cfg.initial_energy_mev <= 0. || cfg.source_bin_mm <= 0.) {
    throw std::runtime_error("population and active cycles must be positive; inactive cycles non-negative");
  }
  cfg.initial_positions_mm = cfg.source_points_path.empty()
      ? std::vector<G4ThreeVector>{cfg.initial_position_mm}
      : ReadSourcePoints(cfg.source_points_path);
  return cfg;
}

G4ThreeVector IsotropicDirection() {
  const double z = 2.0 * G4UniformRand() - 1.0;
  const double phi = CLHEP::twopi * G4UniformRand();
  const double r = std::sqrt(std::max(0.0, 1.0 - z * z));
  return {r * std::cos(phi), r * std::sin(phi), z};
}

class FissionBank {
 public:
  void Clear() {
    particles_.clear();
    fission_event_weight_ = 0.;
    weighted_incident_energy_ = 0.;
    step_fission_neutron_weight_ = 0.;
    target_fission_weights_.clear();
  }
  void Add(const G4Track& track) {
    particles_.push_back({track.GetPosition(), track.GetMomentumDirection(), track.GetKineticEnergy(),
                          track.GetWeight()});
  }
  const std::vector<SourceParticle>& particles() const { return particles_; }
  double TotalWeight() const {
    double total = 0.;
    for (const auto& particle : particles_) total += std::max(0., particle.weight);
    return total;
  }
  long NonUnitWeightCount() const {
    long count = 0;
    for (const auto& particle : particles_) {
      if (std::abs(particle.weight - 1.) > 1.e-12) ++count;
    }
    return count;
  }
  void RecordFissionEvent(double incident_energy, double weight,
                          double secondary_neutron_weight, int target_z, int target_a) {
    const double positive_weight = std::max(0., weight);
    fission_event_weight_ += positive_weight;
    weighted_incident_energy_ += positive_weight * incident_energy;
    step_fission_neutron_weight_ += std::max(0., secondary_neutron_weight);
    target_fission_weights_[{target_z, target_a}] += positive_weight;
  }
  double FissionEventWeight() const { return fission_event_weight_; }
  double MeanIncidentFissionEnergy() const {
    return fission_event_weight_ > 0. ? weighted_incident_energy_ / fission_event_weight_ : 0.;
  }
  double StepFissionNeutronWeight() const { return step_fission_neutron_weight_; }
  const std::map<std::pair<int, int>, double>& TargetFissionWeights() const {
    return target_fission_weights_;
  }
 private:
  std::vector<SourceParticle> particles_;
  double fission_event_weight_ = 0.;
  double weighted_incident_energy_ = 0.;
  double step_fission_neutron_weight_ = 0.;
  std::map<std::pair<int, int>, double> target_fission_weights_;
};

struct SourceDiversity {
  long occupied_bins = 0;
  double shannon_entropy = 0.;
};

SourceDiversity SpatialDiversity(const std::vector<SourceParticle>& particles, double bin_mm) {
  std::map<std::tuple<long, long, long>, long> bins;
  for (const auto& particle : particles) {
    const auto key = std::make_tuple(
        static_cast<long>(std::floor(particle.position.x() / (bin_mm * mm))),
        static_cast<long>(std::floor(particle.position.y() / (bin_mm * mm))),
        static_cast<long>(std::floor(particle.position.z() / (bin_mm * mm))));
    ++bins[key];
  }
  SourceDiversity result;
  result.occupied_bins = static_cast<long>(bins.size());
  if (particles.empty()) return result;
  const double count = static_cast<double>(particles.size());
  for (const auto& entry : bins) {
    const double probability = static_cast<double>(entry.second) / count;
    result.shannon_entropy -= probability * std::log(probability);
  }
  return result;
}

std::vector<SourceParticle> CombFissionBank(const std::vector<SourceParticle>& bank,
                                            long population) {
  if (bank.empty()) throw std::runtime_error("fission source extinguished");
  double total_weight = 0.;
  for (const auto& particle : bank) total_weight += std::max(0., particle.weight);
  if (total_weight <= 0.) throw std::runtime_error("fission bank has non-positive total weight");

  const double step = total_weight / static_cast<double>(population);
  double target = G4UniformRand() * step;
  double cumulative = std::max(0., bank.front().weight);
  std::size_t index = 0;
  std::vector<SourceParticle> next;
  next.reserve(static_cast<std::size_t>(population));
  for (long sample = 0; sample < population; ++sample) {
    while (index + 1 < bank.size() && target >= cumulative) {
      ++index;
      cumulative += std::max(0., bank[index].weight);
    }
    auto particle = bank[index];
    particle.weight = 1.;
    next.push_back(particle);
    target += step;
  }
  return next;
}

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

class SourceGenerator final : public G4VUserPrimaryGeneratorAction {
 public:
  explicit SourceGenerator(std::shared_ptr<std::vector<SourceParticle>> source)
      : source_(std::move(source)), gun_(1) {
    auto* neutron = G4ParticleTable::GetParticleTable()->FindParticle("neutron");
    if (!neutron) throw std::runtime_error("Geant4 neutron definition unavailable");
    gun_.SetParticleDefinition(neutron);
  }
  void GeneratePrimaries(G4Event* event) override {
    if (source_->empty()) throw std::runtime_error("empty source bank");
    // Event identifiers are not guaranteed to restart from zero after a
    // successive BeamOn call.  Source-bank selection is cyclic per generation.
    const auto index = static_cast<std::size_t>(event->GetEventID()) % source_->size();
    const auto& particle = source_->at(index);
    gun_.SetParticlePosition(particle.position);
    gun_.SetParticleMomentumDirection(particle.direction);
    gun_.SetParticleEnergy(particle.energy);
    gun_.SetParticleWeight(particle.weight);
    gun_.GeneratePrimaryVertex(event);
  }
 private:
  std::shared_ptr<std::vector<SourceParticle>> source_;
  G4ParticleGun gun_;
};

class FissionStackingAction final : public G4UserStackingAction {
 public:
  explicit FissionStackingAction(std::shared_ptr<FissionBank> bank) : bank_(std::move(bank)) {}
  G4ClassificationOfNewTrack ClassifyNewTrack(const G4Track* track) override {
    if (track->GetDefinition()->GetParticleName() != "neutron") return fUrgent;
    const auto* creator = track->GetCreatorProcess();
    if (!creator || creator->GetProcessName() != "nFission") return fUrgent;
    bank_->Add(*track);
    // Fission neutrons constitute the next generation.  Killing them in the
    // present event prevents a chain reaction within one source history.
    return fKill;
  }
 private:
  std::shared_ptr<FissionBank> bank_;
};

class FissionSteppingAction final : public G4UserSteppingAction {
 public:
  explicit FissionSteppingAction(std::shared_ptr<FissionBank> bank) : bank_(std::move(bank)) {}
  void UserSteppingAction(const G4Step* step) override {
    if (step->GetTrack()->GetDefinition()->GetParticleName() != "neutron") return;
    const auto* process = step->GetPostStepPoint()->GetProcessDefinedStep();
    if (!process || process->GetProcessName() != "nFission") return;
    double secondary_neutron_weight = 0.;
    for (const auto* secondary : *step->GetSecondaryInCurrentStep()) {
      if (secondary->GetDefinition()->GetParticleName() == "neutron") {
        secondary_neutron_weight += std::max(0., secondary->GetWeight());
      }
    }
    int target_z = 0;
    int target_a = 0;
    if (const auto* hadronic = dynamic_cast<const G4HadronicProcess*>(process)) {
      target_z = hadronic->GetTargetNucleus()->GetZ_asInt();
      target_a = hadronic->GetTargetNucleus()->GetA_asInt();
    }
    bank_->RecordFissionEvent(step->GetPreStepPoint()->GetKineticEnergy(),
                              step->GetPreStepPoint()->GetWeight(), secondary_neutron_weight,
                              target_z, target_a);
  }
 private:
  std::shared_ptr<FissionBank> bank_;
};

class ActionInitialization final : public G4VUserActionInitialization {
 public:
  ActionInitialization(std::shared_ptr<std::vector<SourceParticle>> source,
                       std::shared_ptr<FissionBank> bank)
      : source_(std::move(source)), bank_(std::move(bank)) {}
  void Build() const override {
    SetUserAction(new SourceGenerator(source_));
    SetUserAction(new FissionStackingAction(bank_));
    SetUserAction(new FissionSteppingAction(bank_));
  }
 private:
  std::shared_ptr<std::vector<SourceParticle>> source_;
  std::shared_ptr<FissionBank> bank_;
};

void ReportSourceLocations(const std::vector<G4ThreeVector>& positions) {
  auto* navigator = G4TransportationManager::GetTransportationManager()
                        ->GetNavigatorForTracking();
  for (const auto& position : positions) {
    auto* volume = navigator->LocateGlobalPointAndSetup(position, nullptr, false);
    const auto* logical = volume ? volume->GetLogicalVolume() : nullptr;
    std::cout << "MCGEOBRIDGE_CRITICALITY_LOCATION position_mm="
              << position.x() / mm << "," << position.y() / mm << ","
              << position.z() / mm << " volume="
              << (volume ? volume->GetName() : "none")
              << " material=" << (logical ? logical->GetMaterial()->GetName() : "none")
              << std::endl;
  }
}

double Mean(const std::vector<double>& values) {
  return std::accumulate(values.begin(), values.end(), 0.0) / values.size();
}

double StandardError(const std::vector<double>& values) {
  if (values.size() < 2) return 0.0;
  const double mean = Mean(values);
  double sum = 0.0;
  for (const double value : values) sum += (value - mean) * (value - mean);
  return std::sqrt(sum / (values.size() * (values.size() - 1)));
}

void WriteProgress(const Config& cfg, long cycle, double keff, long produced,
                   double fission_weight, long nonunit_weight_count,
                   double fission_event_weight, double mean_neutrons_per_fission,
                   double step_fission_neutron_weight,
                   double mean_incident_fission_energy_mev,
                   const SourceDiversity& diversity) {
  std::ofstream out(cfg.output + ".progress.json");
  if (!out) return;
  out << std::setprecision(12);
  out << "{\n  \"status\": \"running\",\n"
      << "  \"cycle\": " << cycle << ",\n"
      << "  \"cycle_keff\": " << keff << ",\n"
      << "  \"fission_neutrons\": " << produced << ",\n"
      << "  \"fission_weight\": " << fission_weight << ",\n"
      << "  \"nonunit_fission_weight_count\": " << nonunit_weight_count << ",\n"
      << "  \"fission_event_weight\": " << fission_event_weight << ",\n"
      << "  \"mean_neutrons_per_fission\": " << mean_neutrons_per_fission << ",\n"
      << "  \"step_fission_neutron_weight\": " << step_fission_neutron_weight << ",\n"
      << "  \"mean_incident_fission_energy_mev\": " << mean_incident_fission_energy_mev << ",\n"
      << "  \"source_occupied_bins\": " << diversity.occupied_bins << ",\n"
      << "  \"source_entropy\": " << diversity.shannon_entropy << "\n}\n";
}

struct CycleDiagnostic {
  long cycle;
  double keff;
  long fission_neutrons;
  double fission_weight;
  long nonunit_fission_weight_count;
  double fission_event_weight;
  double mean_neutrons_per_fission;
  double step_fission_neutron_weight;
  double mean_incident_fission_energy_mev;
  std::map<std::pair<int, int>, double> fission_target_weights;
  long source_occupied_bins;
  double source_entropy;
};

void WriteResult(const Config& cfg, const std::vector<double>& inactive,
                 const std::vector<double>& active,
                 const std::vector<CycleDiagnostic>& diagnostics) {
  std::ofstream out(cfg.output);
  if (!out) throw std::runtime_error("cannot write result: " + cfg.output);
  out << std::setprecision(12);
  out << "{\n  \"schema_version\": 1,\n  \"status\": \"complete\",\n";
  out << "  \"method\": \"fixed-population fission-source iteration with systematic combing\",\n";
  out << "  \"model\": \"" << cfg.gdml << "\",\n";
  out << "  \"physics_list\": \"" << cfg.physics << "\",\n";
  out << "  \"hp_fission_fragments\": \""
      << (cfg.disable_hp_fission_fragments ? "disabled-after-physics-list-construction"
                                           : "reference-list-default")
      << "\",\n";
  out << "  \"seed\": " << cfg.seed << ",\n";
  out << "  \"population\": " << cfg.population << ",\n";
  out << "  \"inactive_cycles\": " << cfg.inactive << ",\n";
  out << "  \"active_cycles\": " << cfg.active << ",\n";
  out << "  \"initial_source\": {\"point_count\": " << cfg.initial_positions_mm.size()
      << ", \"energy_mev\": " << cfg.initial_energy_mev;
  if (!cfg.source_points_path.empty()) out << ", \"points_file\": \"" << cfg.source_points_path << "\"";
  out << ", \"first_position_mm\": [" << cfg.initial_positions_mm.front().x() << ", "
      << cfg.initial_positions_mm.front().y() << ", " << cfg.initial_positions_mm.front().z() << "]},\n";
  out << "  \"keff\": {\"mean\": " << Mean(active) << ", \"standard_error\": "
      << StandardError(active) << "},\n";
  out << "  \"inactive_cycle_keff\": [";
  for (std::size_t i = 0; i < inactive.size(); ++i) out << (i ? ", " : "") << inactive[i];
  out << "],\n  \"active_cycle_keff\": [";
  for (std::size_t i = 0; i < active.size(); ++i) out << (i ? ", " : "") << active[i];
  out << "],\n  \"cycle_diagnostics\": [\n";
  for (std::size_t i = 0; i < diagnostics.size(); ++i) {
    const auto& item = diagnostics[i];
    out << "    {\"cycle\": " << item.cycle
        << ", \"phase\": \"" << (item.cycle <= cfg.inactive ? "inactive" : "active")
        << "\", \"keff\": " << item.keff
        << ", \"fission_neutrons\": " << item.fission_neutrons
        << ", \"fission_weight\": " << item.fission_weight
        << ", \"nonunit_fission_weight_count\": " << item.nonunit_fission_weight_count
        << ", \"fission_event_weight\": " << item.fission_event_weight
        << ", \"mean_neutrons_per_fission\": " << item.mean_neutrons_per_fission
        << ", \"step_fission_neutron_weight\": " << item.step_fission_neutron_weight
        << ", \"mean_incident_fission_energy_mev\": " << item.mean_incident_fission_energy_mev
        << ", \"fission_target_weights\": {";
    std::size_t target_index = 0;
    for (const auto& target : item.fission_target_weights) {
      if (target_index++) out << ", ";
      out << "\"Z" << target.first.first << "A" << target.first.second << "\": " << target.second;
    }
    out << "}, \"source_occupied_bins\": " << item.source_occupied_bins
        << ", \"source_entropy\": " << item.source_entropy << "}";
    out << (i + 1 == diagnostics.size() ? "\n" : ",\n");
  }
  out << "  ]\n}\n";
}

}  // namespace

int main(int argc, char** argv) {
  try {
    const Config cfg = ParseArgs(argc, argv);
    G4Random::setTheSeed(cfg.seed);
    auto source = std::make_shared<std::vector<SourceParticle>>();
    source->reserve(static_cast<std::size_t>(cfg.population));
    for (long i = 0; i < cfg.population; ++i) {
      const auto& position = cfg.initial_positions_mm[static_cast<std::size_t>(i) % cfg.initial_positions_mm.size()];
      source->push_back({position * mm, IsotropicDirection(), cfg.initial_energy_mev * MeV});
    }
    auto bank = std::make_shared<FissionBank>();
    auto* run_manager = G4RunManagerFactory::CreateRunManager(G4RunManagerType::SerialOnly);
    run_manager->SetVerboseLevel(0);
    run_manager->SetUserInitialization(new DetectorConstruction(cfg.gdml));
    G4PhysListFactory factory;
    auto* physics = factory.GetReferencePhysList(cfg.physics);
    if (!physics) throw std::runtime_error("unknown Geant4 physics list: " + cfg.physics);
    if (cfg.disable_hp_fission_fragments) {
      G4ParticleHPManager::GetInstance()->SetProduceFissionFragments(false);
    }
    physics->SetVerboseLevel(0);
    run_manager->SetUserInitialization(physics);
    run_manager->SetUserInitialization(new ActionInitialization(source, bank));
    run_manager->Initialize();
    if (cfg.locate_only) {
      ReportSourceLocations(cfg.initial_positions_mm);
      G4GeometryManager::GetInstance()->OpenGeometry();
      delete run_manager;
      return 0;
    }

    std::vector<double> inactive_values;
    std::vector<double> active_values;
    std::vector<CycleDiagnostic> diagnostics;
    const long total_cycles = cfg.inactive + cfg.active;
    for (long cycle = 0; cycle < total_cycles; ++cycle) {
      bank->Clear();
      run_manager->BeamOn(cfg.population);
      const auto& produced = bank->particles();
      const double fission_weight = bank->TotalWeight();
      const long nonunit_weight_count = bank->NonUnitWeightCount();
      const double fission_event_weight = bank->FissionEventWeight();
      const double mean_neutrons_per_fission =
          fission_event_weight > 0. ? fission_weight / fission_event_weight : 0.;
      const double step_fission_neutron_weight = bank->StepFissionNeutronWeight();
      const double mean_incident_fission_energy_mev = bank->MeanIncidentFissionEnergy() / MeV;
      const double k_cycle = fission_weight / static_cast<double>(cfg.population);
      if (cycle < cfg.inactive) inactive_values.push_back(k_cycle);
      else active_values.push_back(k_cycle);
      if (produced.empty()) throw std::runtime_error("fission source extinguished");
      *source = CombFissionBank(produced, cfg.population);
      const auto diversity = SpatialDiversity(*source, cfg.source_bin_mm);
      diagnostics.push_back({cycle + 1, k_cycle, static_cast<long>(produced.size()), fission_weight,
                             nonunit_weight_count, fission_event_weight, mean_neutrons_per_fission,
                             step_fission_neutron_weight, mean_incident_fission_energy_mev,
                             bank->TargetFissionWeights(),
                             diversity.occupied_bins, diversity.shannon_entropy});
      WriteProgress(cfg, cycle + 1, k_cycle, static_cast<long>(produced.size()), fission_weight,
                    nonunit_weight_count, fission_event_weight, mean_neutrons_per_fission,
                    step_fission_neutron_weight, mean_incident_fission_energy_mev, diversity);
      std::cout << "MCGEOBRIDGE_CRITICALITY_CYCLE cycle=" << (cycle + 1)
                << " k=" << k_cycle << " produced=" << produced.size()
                << " fission_weight=" << fission_weight
                << " nonunit_weights=" << nonunit_weight_count
                << " fission_events=" << fission_event_weight
                << " mean_nu=" << mean_neutrons_per_fission
                << " step_fission_neutrons=" << step_fission_neutron_weight
                << " mean_fission_energy_mev=" << mean_incident_fission_energy_mev
                << " source_bins=" << diversity.occupied_bins
                << " source_entropy=" << diversity.shannon_entropy << std::endl;
    }
    WriteResult(cfg, inactive_values, active_values, diagnostics);
    G4GeometryManager::GetInstance()->OpenGeometry();
    delete run_manager;
    std::cout << "MCGEOBRIDGE_CRITICALITY_RESULT status=complete keff=" << Mean(active_values)
              << " se=" << StandardError(active_values) << std::endl;
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "MCGEOBRIDGE_CRITICALITY_ERROR " << error.what() << std::endl;
    return 1;
  }
}
