"""Limit a process (the test emulators) to a share of one CPU core (Windows job object, hard cap) and lower its
priority, so automated tests never saturate a core of the machine they run on.

  GSMERGE_CPU   share of one core per emulator (default 0.6 = 60 %); emu.py applies it at launch
  python cpucap.py PID [PID ...] [--share 0.6]     (cap processes that are already running)

Cap a process only ONCE: a second job nests inside the first and its rate counts as a share of the parent's, so two
60 % caps leave about 1-3 % of a core (seen 2026-10-14: the tests crawled).
"""
import ctypes, os, sys
from ctypes import wintypes

JOB_CPU_RATE = 15                                     # JobObjectCpuRateControlInformation
CPU_RATE_ENABLE, CPU_RATE_HARD_CAP = 0x1, 0x4
PROCESS_SET_QUOTA, PROCESS_TERMINATE, PROCESS_SET_INFORMATION = 0x0100, 0x0001, 0x0200
BELOW_NORMAL_PRIORITY_CLASS = 0x4000


class _CpuRate(ctypes.Structure):
    _fields_ = [("ControlFlags", wintypes.DWORD), ("CpuRate", wintypes.DWORD)]


def default_share():
    return float(os.environ.get("GSMERGE_CPU", "0.6"))


def cap(pid, share=None):
    """Hard-cap process pid at `share` of one logical core and set below-normal priority. Returns True on success."""
    if os.name != "nt":
        return False
    share = default_share() if share is None else share
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.OpenProcess.restype = wintypes.HANDLE
    job = k32.CreateJobObjectW(None, None)
    rate = max(1, min(10000, int(share * 10000 / (os.cpu_count() or 1))))   # 1/100 % of the whole machine
    info = _CpuRate(CPU_RATE_ENABLE | CPU_RATE_HARD_CAP, rate)
    ok = bool(k32.SetInformationJobObject(job, JOB_CPU_RATE, ctypes.byref(info), ctypes.sizeof(info)))
    proc = k32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE | PROCESS_SET_INFORMATION, False, pid)
    if not proc:
        k32.CloseHandle(job)
        return False
    ok = ok and bool(k32.AssignProcessToJobObject(job, proc))
    k32.SetPriorityClass(proc, BELOW_NORMAL_PRIORITY_CLASS)
    k32.CloseHandle(proc)
    k32.CloseHandle(job)                              # the job lives on while the process is in it
    return ok


if __name__ == "__main__":
    args = sys.argv[1:]
    share = None
    if "--share" in args:
        i = args.index("--share"); share = float(args[i + 1]); del args[i:i + 2]
    for p in args:
        print(p, "capped" if cap(int(p), share) else "FAILED")
