from setuptools import find_packages, setup

package_name = "q1_bluetooth_remote"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Q1 Developer",
    maintainer_email="developer@example.com",
    description="Bluetooth remote input tools for PrimeBot Q1",
    license="Apache-2.0",
    entry_points={
        "console_scripts": [
            "key_capture = q1_bluetooth_remote.key_capture:main",
            "walk_control = q1_bluetooth_remote.walk_control:main",
            "remote_profiles = q1_bluetooth_remote.remote_profiles:main",
            "remote_supervisor = q1_bluetooth_remote.remote_supervisor:main",
        ],
    },
)
