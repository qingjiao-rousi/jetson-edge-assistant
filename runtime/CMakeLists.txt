set(EDGEOMNI_LLAMA_UPSTREAM_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../third_party/llama.cpp-omni")

set(EDGEOMNI_LLAMA_BUILD_DIR "${EDGEOMNI_LLAMA_UPSTREAM_DIR}/build-jetson-release" CACHE PATH
    "Existing frozen llama.cpp build directory")
set(EDGEOMNI_LLAMA_INCLUDE_DIR "${EDGEOMNI_LLAMA_UPSTREAM_DIR}/include" CACHE PATH
    "Frozen llama.cpp public include directory")

find_package(OpenSSL REQUIRED)

# The frozen upstream build creates target `llama` (src/CMakeLists.txt:11-55).
# Its build-tree package is not relocatable, so import the verified build artifact directly.
if(EDGEOMNI_BUILD_RELOCATABLE_BUNDLE)
    add_library(edgeomni_llama INTERFACE)
    target_link_libraries(edgeomni_llama INTERFACE llama)
    target_include_directories(edgeomni_llama INTERFACE "${EDGEOMNI_LLAMA_INCLUDE_DIR};${EDGEOMNI_LLAMA_UPSTREAM_DIR}/ggml/include")
    add_library(edgeomni_mtmd INTERFACE)
    target_link_libraries(edgeomni_mtmd INTERFACE mtmd)
    target_include_directories(edgeomni_mtmd INTERFACE "${EDGEOMNI_LLAMA_UPSTREAM_DIR}/tools/mtmd;${EDGEOMNI_LLAMA_INCLUDE_DIR};${EDGEOMNI_LLAMA_UPSTREAM_DIR}/ggml/include")
else()
    find_library(EDGEOMNI_LLAMA_LIBRARY NAMES llama libllama.so PATHS "${EDGEOMNI_LLAMA_BUILD_DIR}/bin" NO_DEFAULT_PATH REQUIRED)
    find_library(EDGEOMNI_MTMD_LIBRARY NAMES mtmd libmtmd.so PATHS "${EDGEOMNI_LLAMA_BUILD_DIR}/bin" NO_DEFAULT_PATH REQUIRED)
    add_library(edgeomni_llama SHARED IMPORTED GLOBAL)
    set_target_properties(edgeomni_llama PROPERTIES IMPORTED_LOCATION "${EDGEOMNI_LLAMA_LIBRARY}" INTERFACE_INCLUDE_DIRECTORIES "${EDGEOMNI_LLAMA_INCLUDE_DIR};${EDGEOMNI_LLAMA_UPSTREAM_DIR}/ggml/include")
    add_library(edgeomni_mtmd SHARED IMPORTED GLOBAL)
    set_target_properties(edgeomni_mtmd PROPERTIES IMPORTED_LOCATION "${EDGEOMNI_MTMD_LIBRARY}" INTERFACE_INCLUDE_DIRECTORIES "${EDGEOMNI_LLAMA_UPSTREAM_DIR}/tools/mtmd;${EDGEOMNI_LLAMA_INCLUDE_DIR};${EDGEOMNI_LLAMA_UPSTREAM_DIR}/ggml/include")
endif()

if(EDGEOMNI_BUILD_RELOCATABLE_BUNDLE)
    message(STATUS "EdgeOmni relocatable upstream targets: llama, mtmd")
else()
    message(STATUS "EdgeOmni frozen llama include: ${EDGEOMNI_LLAMA_INCLUDE_DIR}")
    message(STATUS "EdgeOmni frozen llama library: ${EDGEOMNI_LLAMA_LIBRARY}")
    message(STATUS "EdgeOmni frozen mtmd library: ${EDGEOMNI_MTMD_LIBRARY}")
endif()

add_library(edgeomni_runtime STATIC
    src/chat_template_renderer.cpp
    src/llama_backend_lifecycle.cpp
    src/direct_backend.cpp
    src/mtmd_backend.cpp
    src/vlm_input_validator.cpp
    src/vlm_asset_verifier.cpp)
target_compile_features(edgeomni_runtime PUBLIC cxx_std_17)
target_include_directories(edgeomni_runtime PUBLIC include)
target_link_libraries(edgeomni_runtime PRIVATE edgeomni_llama edgeomni_mtmd OpenSSL::Crypto)

add_library(edgeomni_fake_backend STATIC src/fake_backend.cpp)
target_compile_features(edgeomni_fake_backend PUBLIC cxx_std_17)
target_include_directories(edgeomni_fake_backend PUBLIC include)

find_package(Threads REQUIRED)
add_library(edgeomni_cpp_httplib STATIC
    "${EDGEOMNI_LLAMA_UPSTREAM_DIR}/vendor/cpp-httplib/httplib_stub.cpp")
target_include_directories(edgeomni_cpp_httplib PUBLIC
    "${EDGEOMNI_LLAMA_UPSTREAM_DIR}/vendor/cpp-httplib")
target_compile_features(edgeomni_cpp_httplib PRIVATE cxx_std_17)
target_link_libraries(edgeomni_cpp_httplib PRIVATE Threads::Threads)

add_library(edgeomni_service STATIC src/service.cpp)
target_compile_features(edgeomni_service PUBLIC cxx_std_17)
target_include_directories(edgeomni_service PUBLIC include
    "${EDGEOMNI_LLAMA_UPSTREAM_DIR}/vendor")
target_link_libraries(edgeomni_service PUBLIC edgeomni_runtime edgeomni_cpp_httplib Threads::Threads)

if(EDGEOMNI_BUILD_BENCHMARK_TOOLS)
    add_executable(edgeomni_qwen3_benchmark_runner tools/qwen3_benchmark_runner.cpp)
    target_compile_features(edgeomni_qwen3_benchmark_runner PRIVATE cxx_std_17)
    target_include_directories(edgeomni_qwen3_benchmark_runner PRIVATE
        "${EDGEOMNI_LLAMA_UPSTREAM_DIR}/vendor")
    target_link_libraries(edgeomni_qwen3_benchmark_runner PRIVATE edgeomni_runtime)
    set_target_properties(edgeomni_qwen3_benchmark_runner PROPERTIES
        BUILD_RPATH "${EDGEOMNI_LLAMA_BUILD_DIR}/bin")
    add_executable(edgeomni_vlm_adapter_smoke_runner tools/vlm_adapter_smoke_runner.cpp)
    target_compile_features(edgeomni_vlm_adapter_smoke_runner PRIVATE cxx_std_17)
    target_link_libraries(edgeomni_vlm_adapter_smoke_runner PRIVATE edgeomni_runtime)
    set_target_properties(edgeomni_vlm_adapter_smoke_runner PROPERTIES
        BUILD_RPATH "${EDGEOMNI_LLAMA_BUILD_DIR}/bin")
    add_executable(edgeomni_vlm_service_host tools/vlm_service_host.cpp)
    target_compile_features(edgeomni_vlm_service_host PRIVATE cxx_std_17)
    target_link_libraries(edgeomni_vlm_service_host PRIVATE edgeomni_service)
    set_target_properties(edgeomni_vlm_service_host PROPERTIES
        BUILD_RPATH "${EDGEOMNI_LLAMA_BUILD_DIR}/bin")
endif()

if(EDGEOMNI_BUILD_TESTS)
    add_executable(edgeomni_runtime_unit_test tests/runtime_unit_test.cpp)
    target_compile_features(edgeomni_runtime_unit_test PRIVATE cxx_std_17)
    target_link_libraries(edgeomni_runtime_unit_test PRIVATE edgeomni_runtime edgeomni_fake_backend)
    add_test(NAME edgeomni_runtime_unit_test COMMAND edgeomni_runtime_unit_test)
    add_executable(edgeomni_service_unit_test tests/service_unit_test.cpp)
    target_compile_features(edgeomni_service_unit_test PRIVATE cxx_std_17)
    target_link_libraries(edgeomni_service_unit_test PRIVATE edgeomni_service edgeomni_fake_backend edgeomni_cpp_httplib)
    add_test(NAME edgeomni_service_unit_test COMMAND edgeomni_service_unit_test)
    # 77 is emitted only before HTTP assertions when the test cannot create a
    # temporary 127.0.0.1 socket. Protocol and assertion failures remain FAIL.
    set_tests_properties(edgeomni_service_unit_test PROPERTIES SKIP_RETURN_CODE 77)
    add_executable(edgeomni_vlm_contract_unit_test tests/vlm_contract_unit_test.cpp)
    target_compile_features(edgeomni_vlm_contract_unit_test PRIVATE cxx_std_17)
    target_link_libraries(edgeomni_vlm_contract_unit_test PRIVATE edgeomni_runtime edgeomni_fake_backend)
    add_test(NAME edgeomni_vlm_contract_unit_test COMMAND edgeomni_vlm_contract_unit_test)
    add_executable(edgeomni_mtmd_backend_unit_test tests/mtmd_backend_unit_test.cpp)
    target_compile_features(edgeomni_mtmd_backend_unit_test PRIVATE cxx_std_17)
    target_link_libraries(edgeomni_mtmd_backend_unit_test PRIVATE edgeomni_runtime)
    add_test(NAME edgeomni_mtmd_backend_unit_test COMMAND edgeomni_mtmd_backend_unit_test)
    if(EDGEOMNI_BUILD_BENCHMARK_TOOLS)
        add_test(NAME edgeomni_qwen3_benchmark_runner_cli_test
            COMMAND $<TARGET_FILE:edgeomni_qwen3_benchmark_runner> --help)
        set_tests_properties(edgeomni_qwen3_benchmark_runner_cli_test PROPERTIES
            PASS_REGULAR_EXPRESSION "--session-id.*--prompt-2")
    endif()
endif()

if(EDGEOMNI_BUILD_INTEGRATION)
    add_executable(edgeomni_qwen3_integration_test tests/qwen3_integration_test.cpp)
    target_compile_features(edgeomni_qwen3_integration_test PRIVATE cxx_std_17)
    target_link_libraries(edgeomni_qwen3_integration_test PRIVATE edgeomni_runtime)
    set_target_properties(edgeomni_qwen3_integration_test PROPERTIES
        BUILD_RPATH "${EDGEOMNI_LLAMA_BUILD_DIR}/bin")
endif()
