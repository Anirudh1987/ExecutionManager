#!/usr/bin/env python3
"""Start the ExecutionManager web application.

Usage:
    python run.py

Then open http://localhost:8000 in your browser.
"""

import subprocess
import sys


def main():
    # Install dependencies if needed
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError:
        print("Installing dependencies...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-e", "."])

    import uvicorn

    print("\n  ExecutionManager starting...")
    print("  Open http://localhost:8000 in your browser\n")

    uvicorn.run(
        "src.api.app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )


if __name__ == "__main__":
    main()
