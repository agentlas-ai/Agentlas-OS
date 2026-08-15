#!/usr/bin/env python3
"""Thin wrapper: the drift detector lives in agentlas_cloud/runtime_drift.py so the
installed runtime home carries it (agentlas-one runs it daily on the user's machine).
Same CLI: --registry --acp-registry --matrix --previous-matrix --json --write --quiet.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agentlas_cloud.runtime_drift import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
