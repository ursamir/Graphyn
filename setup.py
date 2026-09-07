"""
Setup script for the graphyn-sdk package.

Authoritative dependency model
------------------------------
``setup.py`` ``install_requires`` + ``extras_require`` is the **source of truth**
for which packages Graphyn declares. ``requirements.txt`` mirrors the default
runtime set with deployment-oriented pins (used by Docker). Keep the two in
sync: after changing install_requires, update requirements.txt and run
``scripts/check_deps.py``.

Optional surfaces (Redis, MCP SDK, HuggingFace, TensorFlow, webrtcvad,
watchfiles) live in extras — not the default install — so a clean
``pip install -e .`` succeeds without system CPython headers or heavy ML
stacks. Install extras as needed, e.g. ``pip install -e ".[dev,mcp]"``.
"""

from setuptools import setup, find_packages

# Default runtime — every direct third-party import under app/ that is required
# for API / CLI / SDK / core plugin loading (not optional backends).
_INSTALL_REQUIRES = [
    # API / models
    "fastapi~=0.115.6",
    "uvicorn[standard]~=0.32.1",
    "python-multipart~=0.0.20",
    "pydantic~=2.10.6",
    "pyyaml~=6.0.2",
    # Platform HTTP + plugin version math (direct imports)
    "httpx>=0.27.0,<1",
    "packaging>=23.0",
    # Audio / numeric stack used by domain + first-party plugins on the host
    # (numpy lower bound kept for 3.10; upper open so 3.13 wheels resolve)
    "numpy>=1.26.4,<3",
    "scipy>=1.14.1,<2",
    "librosa~=0.10.2",
    "soundfile~=0.12.1",
    "noisereduce~=3.0.3",
    "pyloudnorm>=0.1.1",
    # TOML: stdlib tomllib on 3.11+; tomli backport for 3.10
    "tomli>=2.0.1; python_version < '3.11'",
]

_EXTRAS = {
    "dev": [
        "pytest~=8.3.5",
        "pytest-asyncio>=0.24.0",
        "hypothesis~=6.131.15",
    ],
    "mcp": [
        # Official MCP Python SDK (app.mcp.server hard-imports `mcp`)
        "mcp>=1.2.0,<3",
    ],
    "redis": [
        "redis>=5.0.0,<9",
    ],
    "events": [
        # Optional FileWatcherSource backend (polling fallback if absent)
        "watchfiles>=0.21.0",
    ],
    "vad": [
        # Optional segmenter backend; needs a C compiler + Python headers
        "webrtcvad~=2.0.10",
    ],
    "hf": [
        "datasets>=2.14.0",
        "huggingface_hub>=0.16.0",
    ],
    "tf": [
        "tensorflow>=2.13.0",
    ],
}

_EXTRAS["all"] = sorted(
    {
        *_EXTRAS["dev"],
        *_EXTRAS["mcp"],
        *_EXTRAS["redis"],
        *_EXTRAS["events"],
        *_EXTRAS["vad"],
        *_EXTRAS["hf"],
        *_EXTRAS["tf"],
    }
)

setup(
    name="graphyn-sdk",
    version="0.1.0",
    description="Python SDK for the Graphyn AI/Workflow Pipeline Engine",
    long_description=open("README.md", encoding="utf-8").read()
    if __import__("os").path.exists("README.md")
    else "",
    long_description_content_type="text/markdown",
    packages=find_packages(
        exclude=["tests*", "venv*", "graphyn-ui*", "audiobuilder*", "unit_test*"]
    ),
    python_requires=">=3.10",
    install_requires=_INSTALL_REQUIRES,
    extras_require=_EXTRAS,
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
