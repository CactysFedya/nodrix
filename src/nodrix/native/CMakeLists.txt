cmake_minimum_required(VERSION 3.20)
project(nodrix_native VERSION 1.8.0 LANGUAGES CXX)

option(NODRIX_NATIVE_LTO "Enable link-time optimization" ON)
option(NODRIX_NATIVE_MARCH_NATIVE "Tune for the build machine" OFF)
option(NODRIX_BUILD_EXAMPLE_PLUGIN "Build the example native plugin" ON)
option(NODRIX_BUILD_TESTS "Build native core tests" ON)
option(NODRIX_NATIVE_SANITIZERS "Enable AddressSanitizer and UndefinedBehaviorSanitizer" OFF)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

add_library(nodrix_native_sdk INTERFACE)
target_include_directories(nodrix_native_sdk INTERFACE ${CMAKE_CURRENT_SOURCE_DIR}/include)


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

add_executable(nodrix-native-runner
  src/runner.cpp
  src/builtin_nodes.cpp
)
target_link_libraries(nodrix-native-runner PRIVATE nodrix_native_sdk)
target_compile_definitions(nodrix-native-runner PRIVATE NODRIX_NATIVE_VERSION="${PROJECT_VERSION}")
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
endif()

install(TARGETS nodrix-native-runner RUNTIME DESTINATION bin)
install(DIRECTORY include/ DESTINATION include)

if(NODRIX_BUILD_TESTS)
  enable_testing()
  add_executable(nodrix-native-core-test tests/test_core.cpp)
  target_link_libraries(nodrix-native-core-test PRIVATE nodrix_native_sdk)
  nodrix_enable_sanitizers(nodrix-native-core-test)
  add_test(NAME nodrix-native-core-test COMMAND nodrix-native-core-test)
endif()
