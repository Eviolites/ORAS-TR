"""Install the dependencies for ORAS-TR.

Use --backend to override detection: auto, mps, cuda, rocm, directml, or cpu.
"""

import argparse
import importlib.util
import os
import platform
import shutil
import subprocess
import sys


COMMON_REQUIREMENTS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "requirements.txt"
)


def installed_torch_backend():
    if importlib.util.find_spec("torch") is None:
        return None
    try:
        import torch
    except Exception:
        return None
    if torch.cuda.is_available():
        return "rocm" if torch.version.hip else "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def has_nvidia_gpu():
    return shutil.which("nvidia-smi") is not None


def has_windows_gpu():
    if platform.system() != "Windows":
        return False
    command = [
        "powershell",
        "-NoProfile",
        "-Command",
        "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name",
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    return bool(result.stdout.strip())


def choose_backend(requested):
    if requested != "auto":
        return requested
    existing = installed_torch_backend()
    if existing in {"mps", "cuda", "rocm"}:
        return existing
    if platform.system() == "Darwin" and platform.machine() in {"arm64", "aarch64"}:
        return "mps"
    if has_nvidia_gpu():
        return "cuda"
    if has_windows_gpu():
        return "directml"
    return "cpu"


def pip_install(*arguments):
    command = [sys.executable, "-m", "pip", "install", *arguments]
    print("+", " ".join(command), flush=True)
    subprocess.check_call(command)


def require_supported_torch_python():
    if sys.version_info >= (3, 15):
        raise RuntimeError(
            f"Python {platform.python_version()} is not supported by the available "
            "PyTorch wheels. Install Python 3.12 or 3.13, create a virtual "
            "environment with it, and run this installer again."
        )


def install_backend(backend, cuda_index):
    if backend == "mps":
        require_supported_torch_python()
        if installed_torch_backend() not in {"mps", "cpu"}:
            pip_install("torch")
        return
    if backend == "rocm":
        if installed_torch_backend() != "rocm":
            raise RuntimeError(
                "ROCm was requested but a ROCm-enabled PyTorch is not installed. "
                "Install the ROCm PyTorch wheel for your GPU and rerun this script."
            )
        return
    if backend == "directml":
        require_supported_torch_python()
        pip_install("torch-directml")
        return
    if backend == "cuda":
        require_supported_torch_python()
        if installed_torch_backend() != "cuda":
            pip_install("torch", "--index-url", cuda_index)
        return
    if backend == "cpu":
        require_supported_torch_python()
        if installed_torch_backend() is None:
            pip_install("torch", "--index-url", "https://download.pytorch.org/whl/cpu")
        return
    raise ValueError(f"Unsupported backend: {backend}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backend",
        choices=("auto", "mps", "cuda", "rocm", "directml", "cpu"),
        default=os.environ.get("TRANSLATION_BACKEND", "auto").casefold(),
        help="Backend to install (default: auto, or TRANSLATION_BACKEND).",
    )
    parser.add_argument(
        "--cuda-index",
        default="https://download.pytorch.org/whl/cu128",
        help="PyTorch index URL for NVIDIA CUDA installations.",
    )
    args = parser.parse_args()
    backend = choose_backend(args.backend)
    print(f"Selected backend: {backend}")
    install_backend(backend, args.cuda_index)
    pip_install("-r", COMMON_REQUIREMENTS)
    print("Installation complete. Set TRANSLATION_BACKEND=%s when running the script." % backend)


if __name__ == "__main__":
    main()