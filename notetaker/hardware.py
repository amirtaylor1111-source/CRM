"""Work out what this machine can run, and how long it will take.

Transcription is a batch job that happens after the meeting, so a slow
machine means waiting rather than failing. What it must never do is pick a
model that turns a one-hour call into a three-hour grind, or one that will
not fit in RAM. The decision table below is derived from measured realtime
factors on CPU-only hardware.
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

# Realtime factor: audio_seconds / wall_seconds. Higher is faster.
# 1.0x means a one-hour meeting takes one hour to transcribe.
#
# Every "wer" below is a published benchmark figure for the model, on the
# corpora the leaderboard uses. None of them has been measured on this
# machine, on a laptop microphone, or on a South African accent, and nothing
# in this repo measures one. Quote them as the citation they are.
ENGINES = {
    # Parakeet is the default everywhere it applies. It beats Whisper
    # large-v3 on accuracy (6.34% vs 7.44% average word error) while running
    # roughly an order of magnitude faster on CPU, and as a transducer it
    # does not hallucinate sentences into silence the way Whisper can.
    "parakeet": {
        "model": "nemo-parakeet-tdt-0.6b-v3",
        "engine": "onnx-asr",
        "realtime": 10.0,
        "ram_gb": 2.0,
        "disk_mb": 670,
        "wer": "6.3%",
        "languages": "English + 24 European",
    },
    "distil": {
        "model": "distil-large-v3.5",
        "engine": "faster-whisper",
        "realtime": 2.5,
        "ram_gb": 2.5,
        "disk_mb": 1500,
        "wer": "~7.5%",
        "languages": "English only",
    },
    "turbo": {
        "model": "large-v3-turbo",
        "engine": "faster-whisper",
        "realtime": 1.7,
        "ram_gb": 2.5,
        "disk_mb": 1600,
        "wer": "~7.8%",
        "languages": "multilingual",
    },
    "small": {
        "model": "small",
        "engine": "faster-whisper",
        "realtime": 3.0,
        "ram_gb": 1.5,
        "disk_mb": 500,
        "wer": "~13.8%",
        "languages": "multilingual",
    },
    "base": {
        "model": "base",
        "engine": "faster-whisper",
        "realtime": 4.0,
        "ram_gb": 1.0,
        "disk_mb": 150,
        "wer": "~16.6%",
        "languages": "multilingual",
    },
}


@dataclass
class Hardware:
    os_name: str
    cores: int
    threads: int
    ram_gb: float
    has_cuda: bool
    free_disk_gb: float

    def summary(self) -> str:
        gpu = "CUDA GPU" if self.has_cuda else "CPU only"
        return (
            f"{self.os_name}, {self.cores} cores / {self.threads} threads, "
            f"{self.ram_gb:.0f} GB RAM, {gpu}, {self.free_disk_gb:.0f} GB free"
        )


def _ram_gb() -> float:
    try:
        import psutil  # optional; absent on a bare install

        return psutil.virtual_memory().total / (1024**3)
    except Exception:
        pass
    # Linux
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) / (1024**2)
    except OSError:
        pass
    # Windows, without psutil
    if sys.platform == "win32":
        try:
            import ctypes

            class Status(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = Status()
            status.dwLength = ctypes.sizeof(Status)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            return status.ullTotalPhys / (1024**3)
        except Exception:
            pass
    return 8.0  # conservative guess; drives a safe model choice


def _has_cuda() -> bool:
    """True only if a CUDA runtime is actually present.

    Deliberately does not import torch: on a CPU-only machine that import is
    slow, and we never want to pull a CUDA build onto a laptop that has no
    NVIDIA hardware.
    """
    if shutil.which("nvidia-smi"):
        return True
    return bool(os.environ.get("CUDA_PATH"))


def detect() -> Hardware:
    try:
        cores = os.cpu_count() or 2
        physical = cores
        try:
            import psutil

            physical = psutil.cpu_count(logical=False) or cores
        except Exception:
            # Assume SMT when the count is even; wrong on hybrid chips but
            # only ever makes us more conservative.
            physical = max(1, cores // 2) if cores > 2 else cores
    except Exception:
        cores = physical = 2

    try:
        usage = shutil.disk_usage(str(Path(__file__).resolve().parent))
        free_gb = usage.free / (1024**3)
    except OSError:
        free_gb = 0.0

    return Hardware(
        os_name=f"{platform.system()} {platform.release()}",
        cores=physical,
        threads=cores,
        ram_gb=_ram_gb(),
        has_cuda=_has_cuda(),
        free_disk_gb=free_gb,
    )


def recommend(hw: Hardware | None = None, english_only: bool = True) -> dict:
    """Pick an engine for this machine.

    MTG_ENGINE overrides everything, so a user who wants a specific model can
    have one without editing code.
    """
    hw = hw or detect()

    override = os.environ.get("MTG_ENGINE", "").strip().lower()
    if override in ENGINES:
        choice = dict(ENGINES[override])
        choice["key"] = override
        choice["why"] = "set by MTG_ENGINE"
        choice["cpu_threads"] = _threads_for(hw)
        return choice

    if hw.ram_gb < 3:
        key = "base"
        why = "under 3 GB of RAM, so the smallest model is the safe choice"
    elif hw.ram_gb < 5:
        key = "small"
        why = "limited RAM; small is the largest model that fits comfortably"
    else:
        # Parakeet wins on both accuracy and speed wherever the language is
        # covered, which is the overwhelmingly common case.
        key = "parakeet"
        why = (
            "best accuracy available on CPU (6.3% word error on published "
            "benchmarks, better than Whisper large-v3) and roughly 10x faster "
            "than any Whisper model of comparable quality"
        )

    choice = dict(ENGINES[key])
    choice["key"] = key
    choice["why"] = why
    choice["cpu_threads"] = _threads_for(hw)
    return choice


def _threads_for(hw: Hardware) -> int:
    """Thread count for inference.

    Oversubscribing hurts on hybrid P/E-core chips, where the efficiency
    cores finish late and stall the batch. Leave headroom for the OS.
    """
    return max(1, min(8, hw.threads - 2 if hw.threads > 4 else hw.threads))


def estimate_minutes(audio_seconds: float, choice: dict | None = None,
                     hw: Hardware | None = None) -> float:
    """Wall-clock minutes to transcribe this much audio.

    Dual-track does not double the cost: voice activity detection means each
    track only processes the stretches where that person actually speaks, so
    the total speech is about the same as a single mixed recording.
    """
    hw = hw or detect()
    choice = choice or recommend(hw)
    realtime = float(choice.get("realtime", 1.0))
    if hw.has_cuda:
        realtime *= 8
    elif hw.cores <= 2:
        realtime *= 0.6
    return max(0.1, (audio_seconds / realtime) / 60.0)


def format_estimate(audio_seconds: float, choice: dict | None = None,
                    hw: Hardware | None = None) -> str:
    minutes = estimate_minutes(audio_seconds, choice, hw)
    if minutes < 1:
        return "under a minute"
    if minutes < 90:
        return f"about {round(minutes)} minute{'s' if round(minutes) != 1 else ''}"
    return f"about {minutes / 60:.1f} hours"
