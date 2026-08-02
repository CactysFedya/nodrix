cmake_minimum_required(VERSION 3.20)
project(nodrix_native VERSION 2.2.0 LANGUAGES CXX)
set(NODRIX_RELEASE_VERSION "2.2.0a4" CACHE STRING "Nodrix Python release version")

option(NODRIX_NATIVE_LTO "Enable link-time optimization" ON)
option(NODRIX_NATIVE_MARCH_NATIVE "Tune for the build machine" OFF)
option(NODRIX_BUILD_EXAMPLE_PLUGIN "Build the example native plugin" ON)
option(NODRIX_BUILD_NCNN_PLUGIN "Build the official NCNN provider" OFF)
option(NODRIX_FETCH_NCNN "Fetch pinned NCNN source if unavailable" OFF)
set(
  NODRIX_NCNN_SOURCE_DIR ""
  CACHE PATH "Optional local NCNN source tree for offline builds"
)
option(NODRIX_BUILD_TESTS "Build native core tests" ON)
option(NODRIX_NATIVE_SANITIZERS "Enable AddressSanitizer and UndefinedBehaviorSanitizer" OFF)
option(NODRIX_NATIVE_THREAD_SANITIZER "Enable ThreadSanitizer for native core tests" OFF)

if(NODRIX_NATIVE_SANITIZERS AND NODRIX_NATIVE_THREAD_SANITIZER)
  message(FATAL_ERROR "ASan/UBSan and TSan must use separate builds")
endif()

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

find_package(Threads REQUIRED)

add_library(nodrix_native_sdk INTERFACE)
target_include_directories(nodrix_native_sdk INTERFACE ${CMAKE_CURRENT_SOURCE_DIR}/include)
if(WIN32)
  target_compile_definitions(
    nodrix_native_sdk INTERFACE NOMINMAX WIN32_LEAN_AND_MEAN
  )
endif()


function(nodrix_enable_sanitizers target)
  if(NOT NODRIX_NATIVE_SANITIZERS)
    return()
  endif()
  if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang|AppleClang")
    target_compile_options(${target} PRIVATE -fsanitize=address,undefined -fno-omit-frame-pointer)
    target_link_options(${target} PRIVATE -fsanitize=address,undefined)
  else()
    message(FATAL_ERROR "NODRIX_NATIVE_SANITIZERS requires GCC, Clang, or AppleClang")
  endif()
endfunction()

function(nodrix_enable_thread_sanitizer target)
  if(NOT NODRIX_NATIVE_THREAD_SANITIZER)
    return()
  endif()
  if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(
      ${target} PRIVATE -fsanitize=thread -fno-omit-frame-pointer
    )
    target_link_options(${target} PRIVATE -fsanitize=thread)
  else()
    message(
      FATAL_ERROR
      "NODRIX_NATIVE_THREAD_SANITIZER requires GCC or Clang"
    )
  endif()
endfunction()

add_executable(nodrix-native-runner
  src/runner.cpp
  src/builtin_nodes.cpp
)
target_link_libraries(
  nodrix-native-runner
  PRIVATE nodrix_native_sdk Threads::Threads ${CMAKE_DL_LIBS}
)
target_compile_definitions(nodrix-native-runner PRIVATE NODRIX_NATIVE_VERSION="${NODRIX_RELEASE_VERSION}")
nodrix_enable_sanitizers(nodrix-native-runner)
target_compile_options(nodrix-native-runner PRIVATE
  $<$<CXX_COMPILER_ID:GNU,Clang,AppleClang>:-O3;-DNDEBUG;-fvisibility=hidden;-fno-omit-frame-pointer>
)

if(NODRIX_NATIVE_MARCH_NATIVE AND CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang|AppleClang")
  if(APPLE AND CMAKE_SYSTEM_PROCESSOR MATCHES "arm64|aarch64")
    target_compile_options(nodrix-native-runner PRIVATE -mcpu=native)
  else()
    target_compile_options(nodrix-native-runner PRIVATE -march=native)
  endif()
endif()

if(NODRIX_NATIVE_LTO)
  include(CheckIPOSupported)
  check_ipo_supported(RESULT ipo_supported OUTPUT ipo_error)
  if(ipo_supported)
    set_property(TARGET nodrix-native-runner PROPERTY INTERPROCEDURAL_OPTIMIZATION TRUE)
  endif()
endif()

if(NODRIX_BUILD_NCNN_PLUGIN)
  if(NODRIX_NCNN_SOURCE_DIR)
    set(NCNN_BUILD_TOOLS OFF CACHE BOOL "" FORCE)
    set(NCNN_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
    set(NCNN_BUILD_BENCHMARK OFF CACHE BOOL "" FORCE)
    set(NCNN_BUILD_TESTS OFF CACHE BOOL "" FORCE)
    set(NCNN_VULKAN OFF CACHE BOOL "" FORCE)
    set(NCNN_BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
    add_subdirectory(
      "${NODRIX_NCNN_SOURCE_DIR}"
      "${CMAKE_BINARY_DIR}/_deps/ncnn-build"
      EXCLUDE_FROM_ALL
    )
  else()
    find_package(ncnn CONFIG QUIET)
    if(NOT ncnn_FOUND AND NODRIX_FETCH_NCNN)
      include(FetchContent)
      set(NCNN_BUILD_TOOLS OFF CACHE BOOL "" FORCE)
      set(NCNN_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
      set(NCNN_BUILD_BENCHMARK OFF CACHE BOOL "" FORCE)
      set(NCNN_BUILD_TESTS OFF CACHE BOOL "" FORCE)
      set(NCNN_VULKAN OFF CACHE BOOL "" FORCE)
      set(NCNN_BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
      FetchContent_Declare(
        ncnn
        URL
          https://github.com/Tencent/ncnn/releases/download/20260526/ncnn-20260526-full-source.zip
        URL_HASH
          SHA256=754659d6fe65545cf2ef4483ffb84526fea631f8764c44b150f1601d0fb4004b
        DOWNLOAD_EXTRACT_TIMESTAMP TRUE
      )
      FetchContent_MakeAvailable(ncnn)
    elseif(NOT ncnn_FOUND)
      message(
        FATAL_ERROR
        "NCNN was not found. Set ncnn_DIR, NODRIX_NCNN_SOURCE_DIR, "
        "or enable NODRIX_FETCH_NCNN."
      )
    endif()
  endif()

  add_library(
    nodrix_ncnn_detector
    SHARED src/ncnn_detector_plugin.cpp
  )
  target_link_libraries(
    nodrix_ncnn_detector PRIVATE nodrix_native_sdk ncnn
  )
  nodrix_enable_sanitizers(nodrix_ncnn_detector)
  target_compile_options(
    nodrix_ncnn_detector PRIVATE
    $<$<CXX_COMPILER_ID:GNU,Clang,AppleClang>:-O3;-DNDEBUG;-fvisibility=hidden>
  )
  set_target_properties(
    nodrix_ncnn_detector
    PROPERTIES OUTPUT_NAME nodrix_ncnn_detector
  )
  if(NODRIX_NATIVE_LTO AND ipo_supported)
    set_property(
      TARGET nodrix_ncnn_detector
      PROPERTY INTERPROCEDURAL_OPTIMIZATION TRUE
    )
  endif()
  install(
    TARGETS nodrix_ncnn_detector
    RUNTIME DESTINATION bin
    LIBRARY DESTINATION bin
    ARCHIVE DESTINATION lib
  )
endif()

if(NODRIX_BUILD_EXAMPLE_PLUGIN)
  add_library(nodrix_demo_filter SHARED examples/filter_plugin.cpp)
  target_link_libraries(nodrix_demo_filter PRIVATE nodrix_native_sdk)
  nodrix_enable_sanitizers(nodrix_demo_filter)
  target_compile_options(nodrix_demo_filter PRIVATE
    $<$<CXX_COMPILER_ID:GNU,Clang,AppleClang>:-O3;-DNDEBUG;-fvisibility=hidden>
  )
  set_target_properties(nodrix_demo_filter PROPERTIES OUTPUT_NAME nodrix_demo_filter)
  if(NODRIX_NATIVE_LTO AND ipo_supported)
    set_property(TARGET nodrix_demo_filter PROPERTY INTERPROCEDURAL_OPTIMIZATION TRUE)
  endif()

  add_library(
    nodrix_conformance_plugin
    SHARED examples/conformance_plugin.cpp
  )
  target_link_libraries(
    nodrix_conformance_plugin PRIVATE nodrix_native_sdk
  )
  nodrix_enable_sanitizers(nodrix_conformance_plugin)
  target_compile_options(nodrix_conformance_plugin PRIVATE
    $<$<CXX_COMPILER_ID:GNU,Clang,AppleClang>:-O3;-DNDEBUG;-fvisibility=hidden>
  )
  if(NODRIX_NATIVE_LTO AND ipo_supported)
    set_property(
      TARGET nodrix_conformance_plugin
      PROPERTY INTERPROCEDURAL_OPTIMIZATION TRUE
    )
  endif()
endif()

install(TARGETS nodrix-native-runner RUNTIME DESTINATION bin)
install(DIRECTORY include/ DESTINATION include)

if(NODRIX_BUILD_TESTS)
  enable_testing()
  add_executable(nodrix-native-core-test tests/test_core.cpp)
  target_link_libraries(
    nodrix-native-core-test
    PRIVATE nodrix_native_sdk Threads::Threads
  )
  nodrix_enable_sanitizers(nodrix-native-core-test)
  nodrix_enable_thread_sanitizer(nodrix-native-core-test)
  add_test(NAME nodrix-native-core-test COMMAND nodrix-native-core-test)

  add_executable(nodrix-cpp-sdk-test tests/test_cpp_sdk.cpp)
  target_link_libraries(
    nodrix-cpp-sdk-test PRIVATE nodrix_native_sdk
  )
  nodrix_enable_sanitizers(nodrix-cpp-sdk-test)
  add_test(NAME nodrix-cpp-sdk-test COMMAND nodrix-cpp-sdk-test)

  add_executable(
    nodrix-ncnn-detector-test
    tests/test_ncnn_detector.cpp
  )
  target_include_directories(
    nodrix-ncnn-detector-test
    PRIVATE tests/fake_ncnn
  )
  target_link_libraries(
    nodrix-ncnn-detector-test PRIVATE nodrix_native_sdk
  )
  nodrix_enable_sanitizers(nodrix-ncnn-detector-test)
  add_test(
    NAME nodrix-ncnn-detector-test
    COMMAND nodrix-ncnn-detector-test
  )

  add_library(
    nodrix_test_abi_mismatch
    SHARED tests/abi_mismatch_plugin.cpp
  )
  target_link_libraries(
    nodrix_test_abi_mismatch PRIVATE nodrix_native_sdk
  )
  add_library(
    nodrix_test_missing_symbol
    SHARED tests/missing_symbol_plugin.cpp
  )
  target_link_libraries(
    nodrix_test_missing_symbol PRIVATE nodrix_native_sdk
  )
endif()
