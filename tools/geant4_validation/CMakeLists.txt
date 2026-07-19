cmake_minimum_required(VERSION 3.16)
project(mcnp2gdml_g4check LANGUAGES CXX)

find_package(Geant4 REQUIRED gdml)
include(${Geant4_USE_FILE})

add_executable(mcnp2gdml_g4check g4check.cc)
target_compile_features(mcnp2gdml_g4check PRIVATE cxx_std_17)
target_link_libraries(mcnp2gdml_g4check PRIVATE Geant4::G4gdml)
