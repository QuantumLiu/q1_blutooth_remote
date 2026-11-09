from setuptools import find_packages, setup

package_name = "q1_python_template"

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
    description="PrimeBot Q1 Python development package template",
    license="Apache-2.0",
    entry_points={
        "console_scripts": [
            "bms_monitor = q1_python_template.bms_monitor:main",
        ],
    },
)
