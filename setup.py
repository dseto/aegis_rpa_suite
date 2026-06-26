from setuptools import setup, find_packages

setup(
    name="aegis_rpa_suite",
    version="1.0.0",
    description="Engine de Automação, Telemetria e Resiliência Transacional RPA Aegis",
    author="Google DeepMind Team",
    packages=find_packages(),
    install_requires=[
        "playwright",
        "requests",
    ],
    python_requires=">=3.8",
)
