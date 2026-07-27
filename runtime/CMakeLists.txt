set(EDGEOMNI_LLAMA_BUILD_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../third_party/llama.cpp-omni/build-jetson-release" CACHE PATH
    "Existing frozen llama.cpp build directory")
set(EDGEOMNI_LLAMA_INCLUDE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../third_party/llama.cpp-omni/include" CACHE PATH
    "Frozen llama.cpp public include directory")

find_library(EDGEOMNI_LLAMA_LIBRARY NAMES llama libllama.so
    PATHS "${EDGEOMNI_LLAMA_BUILD_DIR}/bin" NO_DEFAULT_PATH REQUIRED)

# The frozen upstream build creates target `llama` (src/CMakeLists.txt:11-55).
# Its build-tree package is not relocatable, so import the verified build artifact directly.
add_library(edgeomni_llama SHARED IMPORTED GLOBAL)
set_target_properties(edgeomni_llama PROPERTIES
    IMPORTED_LOCATION "${EDGEOMNI_LLAMA_LIBRARY}"
    INTERFACE_INCLUDE_DIRECTORIES
        "${EDGEOMNI_LLAMA_INCLUDE_DIR};${CMAKE_CURRENT_SOURCE_DIR}/../third_party/llama.cpp-omni/ggml/include")

message(STATUS "EdgeOmni frozen llama include: ${EDGEOMNI_LLAMA_INCLUDE_DIR}")
message(STATUS "EdgeOmni frozen llama library: ${EDGEOMNI_LLAMA_LIBRARY}")

add_library(edgeomni_runtime STATIC
    src/chat_template_renderer.cpp
    src/direct_backend.cpp)
target_compile_features(edgeomni_runtime PUBLIC cxx_std_17)
target_include_directories(edgeomni_runtime PUBLIC include)
target_link_libraries(edgeomni_runtime PRIVATE edgeomni_llama)

add_library(edgeomni_fake_backend STATIC src/fake_backend.cpp)
target_compile_features(edgeomni_fake_backend PUBLIC cxx_std_17)
target_include_directories(edgeomni_fake_backend PUBLIC include)

find_package(Threads REQUIRED)
add_library(edgeomni_cpp_httplib STATIC
    ../third_party/llama.cpp-omni/vendor/cpp-httplib/httplib_stub.cpp)
target_include_directories(edgeomni_cpp_httplib PUBLIC
    ../third_party/llama.cpp-omni/vendor/cpp-httplib)
target_compile_features(edgeomni_cpp_httplib PRIVATE cxx_std_17)
target_link_libraries(edgeomni_cpp_httplib PRIVATE Threads::Threads)

add_library(edgeomni_service STATIC src/service.cpp)
target_compile_features(edgeomni_service PUBLIC cxx_std_17)
target_include_directories(edgeomni_service PUBLIC include
    ../third_party/llama.cpp-omni/vendor)
target_link_libraries(edgeomni_service PUBLIC edgeomni_runtime edgeomni_cpp_httplib Threads::Threads)

if(EDGEOMNI_BUILD_TESTS)
    add_executable(edgeomni_runtime_unit_test tests/runtime_unit_test.cpp)
    target_compile_features(edgeomni_runtime_unit_test PRIVATE cxx_std_17)
    target_link_libraries(edgeomni_runtime_unit_test PRIVATE edgeomni_runtime edgeomni_fake_backend)
    add_test(NAME edgeomni_runtime_unit_test COMMAND edgeomni_runtime_unit_test)
    add_executable(edgeomni_service_unit_test tests/service_unit_test.cpp)
    target_compile_features(edgeomni_service_unit_test PRIVATE cxx_std_17)
    target_link_libraries(edgeomni_service_unit_test PRIVATE edgeomni_service edgeomni_fake_backend edgeomni_cpp_httplib)
    add_test(NAME edgeomni_service_unit_test COMMAND edgeomni_service_unit_test)
endif()

if(EDGEOMNI_BUILD_INTEGRATION)
    add_executable(edgeomni_qwen3_integration_test tests/qwen3_integration_test.cpp)
    target_compile_features(edgeomni_qwen3_integration_test PRIVATE cxx_std_17)
    target_link_libraries(edgeomni_qwen3_integration_test PRIVATE edgeomni_runtime)
    set_target_properties(edgeomni_qwen3_integration_test PROPERTIES
        BUILD_RPATH "${EDGEOMNI_LLAMA_BUILD_DIR}/bin")
endif()
