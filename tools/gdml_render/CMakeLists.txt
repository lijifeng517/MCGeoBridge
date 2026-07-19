cmake_minimum_required(VERSION 3.16)
project(mcgeobridge_gdml_render LANGUAGES CXX)

find_package(Geant4 REQUIRED gdml)
include(${Geant4_USE_FILE})

add_executable(mcgeobridge_gdml_render render_gdml.cc)
target_compile_features(mcgeobridge_gdml_render PRIVATE cxx_std_17)
target_link_libraries(mcgeobridge_gdml_render PRIVATE
  Geant4::G4RayTracer
  Geant4::G4vis_management
  Geant4::G4modeling
  Geant4::G4physicslists
  Geant4::G4gdml
)

