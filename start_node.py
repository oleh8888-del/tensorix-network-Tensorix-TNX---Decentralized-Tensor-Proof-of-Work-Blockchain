"""
Tensorix Network (TNX) - Node Launcher
Starts the full RPC & P2P daemon on port 8333.
"""

import uvicorn
import os
import sys

# Ensure UTF-8 on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from tensorix.node.server import app

if __name__ == "__main__":
    host = os.environ.get("TENSORIX_HOST", "127.0.0.1")
    port = int(os.environ.get("TENSORIX_PORT", 8333))
    print("=" * 60)
    print("🌐 STARTING TENSORIX NODE (TNX)")
    print(f"Listening on http://{host}:{port} (Local: http://127.0.0.1:{port})")
    print(f"API Docs:     http://127.0.0.1:{port}/docs")
    print("=" * 60)
    uvicorn.run(app, host=host, port=port, log_level="info")

