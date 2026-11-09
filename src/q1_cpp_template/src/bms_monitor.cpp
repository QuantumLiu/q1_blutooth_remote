#include "aimdk_msgs/msg/bms.hpp"
#include "rclcpp/rclcpp.hpp"

#include <memory>

class BmsMonitor : public rclcpp::Node {
public:
  BmsMonitor() : Node("q1_cpp_bms_monitor") {
    subscription_ = create_subscription<aimdk_msgs::msg::Bms>(
        "/aima/hal/bms/state", rclcpp::SensorDataQoS(),
        [this](const aimdk_msgs::msg::Bms::SharedPtr msg) {
          RCLCPP_INFO(get_logger(),
                      "BMS: voltage=%.3f V, current=%.3f A, remaining=%u%%",
                      msg->voltage / 1000.0, msg->current / 1000.0,
                      static_cast<unsigned>(msg->remaining_capacity_percentage));
        });
    RCLCPP_INFO(get_logger(), "Subscribing to /aima/hal/bms/state");
  }

private:
  rclcpp::Subscription<aimdk_msgs::msg::Bms>::SharedPtr subscription_;
};

int main(int argc, char **argv) {
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<BmsMonitor>());
  rclcpp::shutdown();
  return 0;
}
