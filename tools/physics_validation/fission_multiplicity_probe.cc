#include "G4Event.hh"
#include "G4GDMLParser.hh"
#include "G4HadronicProcess.hh"
#include "G4Nucleus.hh"
#include "G4ParticleGun.hh"
#include "G4ParticleHPManager.hh"
#include "G4ParticleTable.hh"
#include "G4PhysListFactory.hh"
#include "G4RunManager.hh"
#include "G4RunManagerFactory.hh"
#include "G4Step.hh"
#include "G4SystemOfUnits.hh"
#include "G4ThreeVector.hh"
#include "G4VUserActionInitialization.hh"
#include "G4VUserDetectorConstruction.hh"
#include "G4VUserPrimaryGeneratorAction.hh"
#include "G4UserSteppingAction.hh"
#include "Randomize.hh"

#include <algorithm>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>

namespace {

struct Config {
  std::string gdml;
  std::string output;
  long events = 10000;
  long seed = 24681357;
  double energy_mev = 1.4585;
  G4ThreeVector position_mm{0., 0., 0.};
  bool disable_hp_fission_fragments = true;
};

long ParseLong(const char* text, const std::string& label) {
  try {
    std::size_t used = 0;
    const long value = std::stol(text, &used);
    if (used != std::string(text).size()) throw std::invalid_argument("trailing");
    return value;
  } catch (...) {
    throw std::runtime_error("invalid " + label + ": " + text);
  }
}

double ParseDouble(const char* text, const std::string& label) {
  try {
    std::size_t used = 0;
    const double value = std::stod(text, &used);
    if (used != std::string(text).size() || !std::isfinite(value)) {
      throw std::invalid_argument("not finite");
    }
    return value;
  } catch (...) {
    throw std::runtime_error("invalid " + label + ": " + text);
  }
}

Config ParseArgs(int argc, char** argv) {
  if (argc < 3) {
    throw std::runtime_error(
        "usage: mcgeobridge_fission_probe MODEL.gdml RESULT.json [options]\n"
        "  --events N --seed N --energy-mev E --position-mm X Y Z\n"
        "  --enable-hp-fission-fragments");
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
    } else if (arg == "--energy-mev") {
      need(1); cfg.energy_mev = ParseDouble(argv[++i], "energy");
    } else if (arg == "--position-mm") {
      need(3);
      cfg.position_mm = {ParseDouble(argv[++i], "source x"),
                         ParseDouble(argv[++i], "source y"),
                         ParseDouble(argv[++i], "source z")};
    } else if (arg == "--enable-hp-fission-fragments") {
      cfg.disable_hp_fission_fragments = false;
    } else {
      throw std::runtime_error("unknown option: " + arg);
    }
  }
  if (cfg.events <= 0 || cfg.energy_mev <= 0.) {
    throw std::runtime_error("events and energy must be positive");
  }
  return cfg;
}

G4ThreeVector IsotropicDirection() {
  const double z = 2. * G4UniformRand() - 1.;
  const double phi = CLHEP::twopi * G4UniformRand();
  const double r = std::sqrt(std::max(0., 1. - z * z));
  return {r * std::cos(phi), r * std::sin(phi), z};
}

class DetectorConstruction final : public G4VUserDetectorConstruction {
 public:
  explicit DetectorConstruction(std::string gdml) : gdml_(std::move(gdml)) {}
  G4VPhysicalVolume* Construct() override {
    parser_.Read(gdml_, false);
    return parser_.GetWorldVolume();
  }
 private:
  std::string gdml_;
  G4GDMLParser parser_;
};

class PrimaryGenerator final : public G4VUserPrimaryGeneratorAction {
 public:
  explicit PrimaryGenerator(const Config& cfg)
      : gun_(1), energy_(cfg.energy_mev * MeV), position_(cfg.position_mm * mm) {
    gun_.SetParticleDefinition(G4ParticleTable::GetParticleTable()->FindParticle("neutron"));
    gun_.SetParticleEnergy(energy_);
    gun_.SetParticlePosition(position_);
  }
  void GeneratePrimaries(G4Event* event) override {
    gun_.SetParticleMomentumDirection(IsotropicDirection());
    gun_.GeneratePrimaryVertex(event);
  }
 private:
  G4ParticleGun gun_;
  double energy_;
  G4ThreeVector position_;
};

struct ProbeResult {
  long first_hadronic_interactions = 0;
  long fission_events = 0;
  long emitted_neutrons = 0;
  long long emitted_neutrons_squared = 0;
  double incident_fission_energy = 0.;
  std::map<std::pair<int, int>, long> fission_targets;
  std::map<std::pair<int, int>, long> target_emitted_neutrons;
};

class FirstInteractionAction final : public G4UserSteppingAction {
 public:
  explicit FirstInteractionAction(std::shared_ptr<ProbeResult> result)
      : result_(std::move(result)) {}
  void UserSteppingAction(const G4Step* step) override {
    const auto* track = step->GetTrack();
    if (track->GetTrackID() != 1 || track->GetDefinition()->GetParticleName() != "neutron") return;
    const auto* process = step->GetPostStepPoint()->GetProcessDefinedStep();
    if (!process || process->GetProcessType() != fHadronic) return;

    ++result_->first_hadronic_interactions;
    if (process->GetProcessName() == "nFission") {
      ++result_->fission_events;
      result_->incident_fission_energy += step->GetPreStepPoint()->GetKineticEnergy();
      long event_neutrons = 0;
      for (const auto* secondary : *step->GetSecondaryInCurrentStep()) {
        if (secondary->GetDefinition()->GetParticleName() == "neutron") {
          ++result_->emitted_neutrons;
          ++event_neutrons;
        }
      }
      result_->emitted_neutrons_squared += event_neutrons * event_neutrons;
      if (const auto* hadronic = dynamic_cast<const G4HadronicProcess*>(process)) {
        if (const auto* nucleus = hadronic->GetTargetNucleus()) {
          const auto target = std::make_pair(nucleus->GetZ_asInt(), nucleus->GetA_asInt());
          ++result_->fission_targets[target];
          result_->target_emitted_neutrons[target] += event_neutrons;
        }
      }
    }
    // Match the Hadr03 diagnostic principle: retain only the primary's first
    // nuclear interaction and discard all descendants from that event.
    G4RunManager::GetRunManager()->AbortEvent();
  }
 private:
  std::shared_ptr<ProbeResult> result_;
};

class ActionInitialization final : public G4VUserActionInitialization {
 public:
  ActionInitialization(Config cfg, std::shared_ptr<ProbeResult> result)
      : cfg_(std::move(cfg)), result_(std::move(result)) {}
  void Build() const override {
    SetUserAction(new PrimaryGenerator(cfg_));
    SetUserAction(new FirstInteractionAction(result_));
  }
 private:
  Config cfg_;
  std::shared_ptr<ProbeResult> result_;
};

void WriteResult(const Config& cfg, const ProbeResult& result) {
  std::ofstream out(cfg.output);
  if (!out) throw std::runtime_error("cannot write result: " + cfg.output);
  const double mean_nu = result.fission_events > 0
      ? static_cast<double>(result.emitted_neutrons) / result.fission_events : 0.;
  const double sample_variance = result.fission_events > 1
      ? (static_cast<double>(result.emitted_neutrons_squared) -
         result.fission_events * mean_nu * mean_nu) / (result.fission_events - 1)
      : 0.;
  const double mean_nu_standard_error = result.fission_events > 0
      ? std::sqrt(std::max(0., sample_variance) / result.fission_events) : 0.;
  const double mean_energy = result.fission_events > 0
      ? result.incident_fission_energy / result.fission_events / MeV : 0.;
  out << std::setprecision(12)
      << "{\n"
      << "  \"model\": \"" << cfg.gdml << "\",\n"
      << "  \"events\": " << cfg.events << ",\n"
      << "  \"seed\": " << cfg.seed << ",\n"
      << "  \"source_energy_mev\": " << cfg.energy_mev << ",\n"
      << "  \"hp_fission_fragments\": "
      << (cfg.disable_hp_fission_fragments ? "false" : "true") << ",\n"
      << "  \"first_hadronic_interactions\": " << result.first_hadronic_interactions << ",\n"
      << "  \"fission_events\": " << result.fission_events << ",\n"
      << "  \"emitted_neutrons\": " << result.emitted_neutrons << ",\n"
      << "  \"mean_neutrons_per_fission\": " << mean_nu << ",\n"
      << "  \"mean_neutrons_per_fission_standard_error\": "
      << mean_nu_standard_error << ",\n"
      << "  \"mean_incident_fission_energy_mev\": " << mean_energy << ",\n"
      << "  \"fission_targets\": {";
  bool first = true;
  for (const auto& [target, count] : result.fission_targets) {
    if (!first) out << ", ";
    first = false;
    out << "\"Z" << target.first << "_A" << target.second << "\": " << count;
  }
  out << "},\n  \"target_mean_neutrons_per_fission\": {";
  first = true;
  for (const auto& [target, count] : result.fission_targets) {
    if (!first) out << ", ";
    first = false;
    const double target_mean = count > 0
        ? static_cast<double>(result.target_emitted_neutrons.at(target)) / count : 0.;
    out << "\"Z" << target.first << "_A" << target.second << "\": " << target_mean;
  }
  out << "}\n}\n";
}

}  // namespace

int main(int argc, char** argv) {
  try {
    const Config cfg = ParseArgs(argc, argv);
    CLHEP::HepRandom::setTheSeed(cfg.seed);
    auto result = std::make_shared<ProbeResult>();
    auto* run_manager = G4RunManagerFactory::CreateRunManager(G4RunManagerType::SerialOnly);
    run_manager->SetVerboseLevel(0);
    run_manager->SetUserInitialization(new DetectorConstruction(cfg.gdml));
    G4PhysListFactory factory;
    auto* physics = factory.GetReferencePhysList("Shielding");
    if (!physics) throw std::runtime_error("Geant4 Shielding physics list is unavailable");
    if (cfg.disable_hp_fission_fragments) {
      G4ParticleHPManager::GetInstance()->SetProduceFissionFragments(false);
    }
    physics->SetVerboseLevel(0);
    run_manager->SetUserInitialization(physics);
    run_manager->SetUserInitialization(new ActionInitialization(cfg, result));
    run_manager->Initialize();
    run_manager->BeamOn(cfg.events);
    WriteResult(cfg, *result);
    delete run_manager;
    std::cout << "fission probe result: " << cfg.output << std::endl;
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "error: " << error.what() << std::endl;
    return 2;
  }
}
