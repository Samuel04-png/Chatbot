"""Headless Chrome smoke via CDP pipe, with synthetic intercepted responses only."""
import subprocess
from pathlib import Path


def test_frontend_browser_workflows():
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run(['node','scripts/test_browser.mjs'],cwd=root,capture_output=True,text=True,timeout=55)
    assert result.returncode==0,result.stdout+result.stderr
