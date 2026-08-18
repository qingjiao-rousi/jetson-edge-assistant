cmake_minimum_required(VERSION 3.20)
project(edgeomni_runtime LANGUAGES CXX)

option(EDGEOMNI_BUILD_TESTS "Build EdgeOmni unit tests" ON)
option(EDGEOMNI_BUILD_INTEGRATION "Build Qwen3 DirectBackend integration test" OFF)
option(EDGEOMNI_BUILD_BENCHMARK_TOOLS "Build DirectBackend benchmark tools" ON)
option(EDGEOMNI_BUILD_RELOCATABLE_BUNDLE "Build an opt-in relocatable offline bundle" OFF)

if(EDGEOMNI_BUILD_RELOCATABLE_BUNDLE)
    include(cmake/EdgeOmniRelocatableBundle.cmake)
    return()
endif()

if(EDGEOMNI_BUILD_TESTS)
    enable_testing()
endif()

add_subdirectory(runtime)
