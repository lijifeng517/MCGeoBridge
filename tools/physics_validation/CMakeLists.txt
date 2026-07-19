cmake_minimum_required(VERSION 3.16)
project(mcgeobridge_transport_validation LANGUAGES CXX)

find_package(Geant4 REQUIRED gdml)
include(${Geant4_USE_FILE})

add_executable(mcgeobridge_transport transport_validation.cc)
target_compile_features(mcgeobridge_transport PRIVATE cxx_std_17)
target_link_libraries(mcgeobridge_transport PRIVATE Geant4::G4physicslists Geant4::G4gdml)

add_executable(mcgeobridge_criticality criticality_validation.cc)
target_compile_features(mcgeobridge_criticality PRIVATE cxx_std_17)
target_link_libraries(mcgeobridge_criticality PRIVATE Geant4::G4physicslists Geant4::G4gdml)

add_executable(mcgeobridge_fission_probe fission_multiplicity_probe.cc)
target_compile_features(mcgeobridge_fission_probe PRIVATE cxx_std_17)
target_link_libraries(mcgeobridge_fission_probe PRIVATE Geant4::G4physicslists Geant4::G4gdml)
