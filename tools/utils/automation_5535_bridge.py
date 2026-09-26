# -*- coding: utf-8 -*-
# Read config once at startup; no network operation during import.
from pathlib import Path
import json, sys

def attach_5535_database(app, web_file):
    config_path = Path(web_file).resolve().parent / "5535_automation.json"
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    if config.get("enabled") is not True:
        return
    home = Path(config["automation_home"]).resolve()
    if not (home / "automation5535" / "web.py").is_file():
        # The optional legacy automation package is absent in the current
        # deployment. The active S02 launcher supplies its own update wrapper;
        # do not import a historical backup just to satisfy this hook.
        print("5535 automation package unavailable; keeping native UI routes", flush=True)
        return
    sys.path.insert(0, str(home))
    from automation5535.web import attach
    attach(app, config_path)
