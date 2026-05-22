"""
Setup script for the graphyn-sdk package.
"""

from setuptools import setup, find_packages

setup(
    name="graphyn-sdk",
    version="0.1.0",
    description="Python SDK for the Graphyn AI/Workflow Pipeline Engine",
    long_description=open("README.md", encoding="utf-8").read() if __import__("os").path.exists("README.md") else "",
    long_description_content_type="text/markdown",
    packages=find_packages(exclude=["tests*", "venv*", "audiobuilder*"]),
    python_requires=">=3.10",
    install_requires=[
        "fastapi>=0.100.0",
        "uvicorn>=0.23.0",
        "pyyaml>=6.0",
        "numpy>=1.24.0",
        "librosa>=0.10.0",
        "soundfile>=0.12.0",
        "scipy>=1.10.0",
        "httpx>=0.24.0",
    ],
    extras_require={
        "hf": [
            "datasets>=2.14.0",
            "huggingface_hub>=0.16.0",
        ],
        "tf": [
            "tensorflow>=2.13.0",
        ],
        "vad": [
            "webrtcvad>=2.0.10",
        ],
        "all": [
            "datasets>=2.14.0",
            "huggingface_hub>=0.16.0",
            "tensorflow>=2.13.0",
            "webrtcvad>=2.0.10",
        ],
    },
    entry_points={
        "console_scripts": [
            "graphyn=app.cli.main:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
