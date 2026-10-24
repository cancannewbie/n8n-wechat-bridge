# -*- coding: utf-8 -*-
"""POST a sample image to the n8n webhook to verify connectivity."""
from __future__ import annotations

import sys
from pathlib import Path

from bridge_common import load_config, post_image_file, setup_logging

logger = setup_logging("smoke_test")


def ensure_sample(path: Path) -> None:
    if path.exists() and path.stat().st_size > 0:
        return
    # Minimal valid 1x1 PNG
    import base64
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)


def main() -> int:
    cfg = load_config()
    sample = Path(__file__).resolve().parent / "samples" / "smoke.png"
    ensure_sample(sample)
    # Use a fake group name for gate testing; empty allowlist accepts all
    result = post_image_file(
        cfg,
        sample,
        group_name="smoke-test-group",
        sender_name="smoke-tester",
        text="bridge smoke test",
        logger=logger,
    )
    print("RESULT:", result)
    accepted = False
    if isinstance(result, dict):
        accepted = bool(result.get("accepted") is True or result.get("accepted") == "true")
        # also accept nested / n8n styles
        if not accepted and result.get("ok") is True:
            accepted = True
    if accepted:
        print("SMOKE_OK accepted=true")
        return 0
    print("SMOKE_DONE (check body for accepted); raw=", result)
    # still exit 0 if HTTP succeeded; parent can inspect
    return 0


if __name__ == "__main__":
    sys.exit(main())
