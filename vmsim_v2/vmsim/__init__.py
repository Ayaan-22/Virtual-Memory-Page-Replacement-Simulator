"""vmsim — virtual memory & page-replacement simulator (v2)."""
from .algorithms import POLICIES, make
from .simulator import Config, Event, Result, simulate, run_all, normalize
from . import workloads, experiments

__version__ = "2.0.0"
__all__ = ["POLICIES", "make", "Config", "Event", "Result", "simulate", "run_all",
           "normalize", "workloads", "experiments"]
