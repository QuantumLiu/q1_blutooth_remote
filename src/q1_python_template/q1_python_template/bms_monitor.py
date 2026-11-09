import rclpy
from aimdk_msgs.msg import Bms
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data


class BmsMonitor(Node):
    def __init__(self):
        super().__init__("q1_python_bms_monitor")
        self.subscription = self.create_subscription(
            Bms,
            "/aima/hal/bms/state",
            self.callback,
            qos_profile_sensor_data,
        )
        self.get_logger().info("Subscribing to /aima/hal/bms/state")

    def callback(self, msg: Bms):
        self.get_logger().info(
            f"BMS: voltage={msg.voltage / 1000.0:.3f} V, "
            f"current={msg.current / 1000.0:.3f} A, "
            f"remaining={msg.remaining_capacity_percentage}%"
        )


def main(args=None):
    rclpy.init(args=args)
    node = BmsMonitor()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
