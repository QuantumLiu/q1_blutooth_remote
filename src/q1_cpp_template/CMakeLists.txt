cmake_minimum_required(VERSION 3.16)
project(q1_cpp_template)

if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 17)
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(aimdk_msgs REQUIRED)

add_executable(bms_monitor src/bms_monitor.cpp)
ament_target_dependencies(bms_monitor rclcpp aimdk_msgs)

install(TARGETS bms_monitor
  DESTINATION lib/${PROJECT_NAME})

ament_package()
