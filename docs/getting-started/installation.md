# Installation

Plyctl 2.3 requires Python 3.11 or newer. Python 3.12 is recommended for development and CI.

## Install the exact branch documented here

```bash
git clone https://github.com/CactysFedya/nodrix.git
cd nodrix
git switch feature/2.3.0-workspace-and-operations

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

Verify the installation:

```bash
plyctl --version
plyctl --help
python -c "import plyctl; print(plyctl.__version__)"
```

Expected version:

```text
2.3.0a1
```

## Install optional capabilities

Install only the extras required by your pipeline:

```bash
# Documentation development
python -m pip install -e '.[docs]'

# Development and tests
python -m pip install -e '.[dev]'

# Vision, media, viewer, or other extras declared by the project
python -m pip install -e '.[vision,media,viewer]'
```

Use the exact extra names from `pyproject.toml`; unavailable platform dependencies should not be installed blindly on constrained devices.

## ROS 2 hosts

Install Plyctl inside a normal Python environment, then load ROS 2 through a workspace environment file rather than modifying every shell manually. A typical environment sources:

```text
/opt/ros/jazzy/setup.bash
$HOME/livox_ws/install/setup.bash
```

The workspace layer deliberately keeps ROS setup scripts outside pipeline YAML.

## Troubleshooting

### `plyctl` is not found

Check that the virtual environment is active and that the package is installed:

```bash
which python
python -m pip show plyctl
python -m plyctl.cli --help
```

### The old `nodrix` command appears

This is expected compatibility behavior in the 2.x series. Prefer `plyctl` in new scripts and documentation.

### Installation stalls before downloading packages

Check DNS, proxy variables, and package-index access. GitHub Actions performs documentation installation in a clean Linux environment, so local documentation dependencies are not required merely to edit Markdown.
