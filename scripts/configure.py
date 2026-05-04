#!/usr/bin/env python3
"""
Interactive configuration tool for AgentDispatch.
Manages models, providers, tier spoofing, and defaults in dispatch.json.

Usage:
    python configure.py              # Configure project dispatch.json
    python configure.py --user       # Configure user ~/.claude/dispatch.json

Launch from Claude Code CLI:
    ! python agent-dispatch/scripts/configure.py
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
DEFAULTS_PATH = PLUGIN_DIR / "config" / "defaults.json"

TIER_OPTIONS = ["sonnet", "haiku", "opus", "none"]
BACKEND_OPTIONS = ["claude-cli", "opencode"]

GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
RED = "\033[31m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def _find_project_root() -> Path:
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / ".git").exists():
            return parent
    return cwd


def _load_json(path: Path) -> dict:
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"  {DIM}Saved: {path}{RESET}")


def _input(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    val = input(f"{prompt}{suffix}: ").strip()
    return val if val else default


def _pick(prompt: str, options: list[str], default: str = "") -> str:
    print(f"\n{prompt}")
    for i, opt in enumerate(options, 1):
        marker = f" {CYAN}(default){RESET}" if opt == default else ""
        print(f"  {i}. {opt}{marker}")
    while True:
        val = input(f"Choice [1-{len(options)}]: ").strip()
        if not val and default:
            return default
        try:
            idx = int(val)
            if 1 <= idx <= len(options):
                return options[idx - 1]
        except ValueError:
            if val in options:
                return val
        print(f"  {RED}Invalid choice{RESET}")


def _confirm(prompt: str, default: bool = True) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    val = input(f"{prompt} {suffix}: ").strip().lower()
    if not val:
        return default
    return val in ("y", "yes")


def _get_ollama_models() -> list[str]:
    if not shutil.which("ollama"):
        return []
    try:
        r = subprocess.run(
            ["ollama", "list"],
            capture_output=True, text=True, timeout=10,
        )
        models = []
        for line in r.stdout.strip().split("\n")[1:]:
            parts = line.split()
            if parts:
                models.append(parts[0])
        return models
    except (subprocess.TimeoutExpired, OSError):
        return []


def _print_header(title: str):
    print(f"\n{BOLD}{'=' * 50}")
    print(f"  {title}")
    print(f"{'=' * 50}{RESET}\n")


def _print_providers(config: dict):
    providers = config.get("providers", {})
    if not providers:
        print(f"  {DIM}No providers configured{RESET}")
        return

    for name, prov in providers.items():
        backend = prov.get("backend", "?")
        base_url = prov.get("base_url", "")
        url_str = f" ({base_url})" if base_url else ""
        print(f"  {BOLD}{name}{RESET} [{backend}]{url_str}")
        models = prov.get("models", {})
        for alias, mcfg in models.items():
            tier = mcfg.get("tier", "")
            tier_str = f" {YELLOW}tier={tier}{RESET}" if tier else ""
            timeout = mcfg.get("timeout", "?")
            print(f"    {CYAN}{alias}{RESET} → {mcfg.get('id', alias)} ({timeout}s){tier_str}")
        print()


def _print_config_summary(config: dict):
    print(f"  Default model: {GREEN}{config.get('default_model', '?')}{RESET}")
    print(f"  Enforce dispatch: {config.get('enforce_dispatch', False)}")
    print(f"  Max concurrent: {config.get('max_concurrent', 4)}")
    print(f"  Audit: {config.get('audit', True)}")
    print()
    _print_providers(config)


# ── Menu actions ──────────────────────────────────────────


def action_list_models(config: dict, config_path: Path):
    _print_header("Current Configuration")
    _print_config_summary(config)


def action_add_ollama_model(config: dict, config_path: Path):
    _print_header("Add Ollama Model")

    ollama_models = _get_ollama_models()
    if ollama_models:
        print(f"  {GREEN}Detected Ollama models:{RESET}")
        for i, m in enumerate(ollama_models, 1):
            print(f"    {i}. {m}")
        print()
        choice = _input("Enter model name or number from list")
        try:
            idx = int(choice)
            if 1 <= idx <= len(ollama_models):
                model_name = ollama_models[idx - 1]
            else:
                model_name = choice
        except ValueError:
            model_name = choice
    else:
        print(f"  {DIM}Ollama not running or no models found{RESET}")
        model_name = _input("Model name (e.g. kimi-k2.6:cloud)")

    if not model_name:
        print(f"  {RED}Cancelled{RESET}")
        return

    # Strip :latest suffix for alias
    alias = model_name.removesuffix(":latest")

    timeout = int(_input("Timeout (seconds)", "3600"))

    tier = _pick("Tier spoofing (makes model appear as this Claude tier):",
                 TIER_OPTIONS, default="none")
    if tier == "none":
        tier = None

    base_url = _input("Ollama base URL", "http://localhost:11434")

    # Ensure ollama provider exists
    providers = config.setdefault("providers", {})
    ollama_prov = providers.setdefault("ollama", {
        "backend": "claude-cli",
        "base_url": base_url,
        "models": {},
    })
    ollama_prov["base_url"] = base_url

    model_cfg = {"id": model_name, "timeout": timeout}
    if tier:
        model_cfg["tier"] = tier

    ollama_prov["models"][alias] = model_cfg
    _save_json(config_path, config)
    print(f"  {GREEN}Added: ollama/{alias}{RESET}")
    if tier:
        print(f"  {YELLOW}Tier spoofing: {tier}{RESET}")


def action_add_openai_model(config: dict, config_path: Path):
    _print_header("Add OpenAI Model")

    model_id = _input("Model ID (e.g. gpt-4.1, gpt-4.1-mini)")
    if not model_id:
        print(f"  {RED}Cancelled{RESET}")
        return

    alias = _input("Alias (short name for dispatch)", model_id)
    timeout = int(_input("Timeout (seconds)", "3600"))

    providers = config.setdefault("providers", {})
    openai_prov = providers.setdefault("openai", {
        "backend": "opencode",
        "opencode_provider": "openai",
        "models": {},
    })

    openai_prov["models"][alias] = {"id": model_id, "timeout": timeout}
    _save_json(config_path, config)
    print(f"  {GREEN}Added: openai/{alias}{RESET}")


def action_add_custom_provider(config: dict, config_path: Path):
    _print_header("Add Custom Provider")

    name = _input("Provider name (e.g. groq, together, fireworks)")
    if not name:
        print(f"  {RED}Cancelled{RESET}")
        return

    backend = _pick("Backend:", BACKEND_OPTIONS, default="opencode")

    prov_cfg = {"backend": backend, "models": {}}

    if backend == "opencode":
        opencode_provider = _input("OpenCode provider name", name)
        prov_cfg["opencode_provider"] = opencode_provider
    elif backend == "claude-cli":
        base_url = _input("API base URL (for local proxy)")
        if base_url:
            prov_cfg["base_url"] = base_url

    model_id = _input("First model ID")
    if model_id:
        alias = _input("Model alias", model_id)
        timeout = int(_input("Timeout (seconds)", "3600"))
        model_cfg = {"id": model_id, "timeout": timeout}

        if backend == "claude-cli" and prov_cfg.get("base_url"):
            tier = _pick("Tier spoofing:", TIER_OPTIONS, default="none")
            if tier != "none":
                model_cfg["tier"] = tier

        prov_cfg["models"][alias] = model_cfg

    providers = config.setdefault("providers", {})
    providers[name] = prov_cfg
    _save_json(config_path, config)
    print(f"  {GREEN}Added provider: {name}{RESET}")


def action_remove_model(config: dict, config_path: Path):
    _print_header("Remove Model")

    all_models = []
    for prov_name, prov in config.get("providers", {}).items():
        for alias in prov.get("models", {}):
            all_models.append((prov_name, alias))

    if not all_models:
        print(f"  {DIM}No models to remove{RESET}")
        return

    print("  Models:")
    for i, (prov, alias) in enumerate(all_models, 1):
        print(f"    {i}. {prov}/{alias}")

    choice = _input("Remove which? (number or provider/alias)")
    try:
        idx = int(choice)
        if 1 <= idx <= len(all_models):
            prov_name, alias = all_models[idx - 1]
        else:
            print(f"  {RED}Invalid{RESET}")
            return
    except ValueError:
        if "/" in choice:
            prov_name, alias = choice.split("/", 1)
        else:
            print(f"  {RED}Use format: provider/alias{RESET}")
            return

    providers = config.get("providers", {})
    if prov_name in providers and alias in providers[prov_name].get("models", {}):
        del providers[prov_name]["models"][alias]
        if not providers[prov_name]["models"]:
            if _confirm(f"  Provider '{prov_name}' has no models. Remove it too?"):
                del providers[prov_name]
        _save_json(config_path, config)
        print(f"  {GREEN}Removed: {prov_name}/{alias}{RESET}")
    else:
        print(f"  {RED}Not found: {prov_name}/{alias}{RESET}")


def action_set_default(config: dict, config_path: Path):
    _print_header("Set Default Model")

    all_models = []
    for prov_name, prov in config.get("providers", {}).items():
        for alias in prov.get("models", {}):
            full = f"{prov_name}/{alias}" if prov_name != "anthropic" else alias
            all_models.append(full)

    current = config.get("default_model", "sonnet")
    print(f"  Current default: {GREEN}{current}{RESET}\n")
    print("  Available models:")
    for i, m in enumerate(all_models, 1):
        marker = f" {CYAN}(current){RESET}" if m == current else ""
        print(f"    {i}. {m}{marker}")

    choice = _input("\nNew default (number or model name)")
    try:
        idx = int(choice)
        if 1 <= idx <= len(all_models):
            choice = all_models[idx - 1]
    except ValueError:
        pass

    config["default_model"] = choice
    _save_json(config_path, config)
    print(f"  {GREEN}Default model set to: {choice}{RESET}")


def action_set_tier(config: dict, config_path: Path):
    _print_header("Set Tier Spoofing")

    ollama_models = []
    for prov_name, prov in config.get("providers", {}).items():
        if prov.get("base_url"):
            for alias, mcfg in prov.get("models", {}).items():
                ollama_models.append((prov_name, alias, mcfg))

    if not ollama_models:
        print(f"  {DIM}No Ollama/proxy models found. Tier spoofing only works with base_url providers.{RESET}")
        return

    print("  Proxy models:")
    for i, (prov, alias, mcfg) in enumerate(ollama_models, 1):
        tier = mcfg.get("tier", "none")
        print(f"    {i}. {prov}/{alias} — tier: {YELLOW}{tier}{RESET}")

    choice = _input("\nWhich model? (number)")
    try:
        idx = int(choice)
        if 1 <= idx <= len(ollama_models):
            prov_name, alias, mcfg = ollama_models[idx - 1]
        else:
            print(f"  {RED}Invalid{RESET}")
            return
    except ValueError:
        print(f"  {RED}Enter a number{RESET}")
        return

    tier = _pick("Tier:", TIER_OPTIONS, default=mcfg.get("tier", "none"))

    if tier == "none":
        mcfg.pop("tier", None)
        print(f"  {GREEN}Removed tier spoofing from {prov_name}/{alias}{RESET}")
    else:
        mcfg["tier"] = tier
        print(f"  {GREEN}Set {prov_name}/{alias} tier to: {tier}{RESET}")

    _save_json(config_path, config)


def action_toggle_enforce(config: dict, config_path: Path):
    current = config.get("enforce_dispatch", False)
    config["enforce_dispatch"] = not current
    _save_json(config_path, config)
    state = f"{GREEN}enabled{RESET}" if config["enforce_dispatch"] else f"{DIM}disabled{RESET}"
    print(f"  Enforce dispatch: {state}")


def action_scan_ollama(config: dict, config_path: Path):
    _print_header("Scan Ollama Models")

    models = _get_ollama_models()
    if not models:
        print(f"  {RED}Ollama not running or no models found{RESET}")
        return

    existing = set()
    for prov in config.get("providers", {}).values():
        for alias in prov.get("models", {}):
            existing.add(alias)

    print(f"  Found {len(models)} Ollama models:\n")
    new_models = []
    for m in models:
        alias = m.removesuffix(":latest")
        status = f"{DIM}(configured){RESET}" if alias in existing else f"{GREEN}NEW{RESET}"
        print(f"    {m} {status}")
        if alias not in existing:
            new_models.append(m)

    if not new_models:
        print(f"\n  {DIM}All models already configured{RESET}")
        return

    if _confirm(f"\n  Add {len(new_models)} new models to config?"):
        providers = config.setdefault("providers", {})
        ollama_prov = providers.setdefault("ollama", {
            "backend": "claude-cli",
            "base_url": "http://localhost:11434",
            "models": {},
        })

        for m in new_models:
            alias = m.removesuffix(":latest")
            is_cloud = ":cloud" in m
            timeout = 3600 if is_cloud else 1800
            model_cfg = {"id": m, "timeout": timeout}
            if is_cloud:
                model_cfg["tier"] = "sonnet"
            ollama_prov["models"][alias] = model_cfg
            tier_str = f" (tier: sonnet)" if is_cloud else ""
            print(f"    {GREEN}+{RESET} {alias}{tier_str}")

        _save_json(config_path, config)


# ── Main menu ─────────────────────────────────────────────


MENU = [
    ("List current configuration", action_list_models),
    ("Add Ollama model", action_add_ollama_model),
    ("Add OpenAI model", action_add_openai_model),
    ("Add custom provider", action_add_custom_provider),
    ("Remove model", action_remove_model),
    ("Set default model", action_set_default),
    ("Set tier spoofing", action_set_tier),
    ("Toggle enforce dispatch", action_toggle_enforce),
    ("Scan Ollama & auto-add new models", action_scan_ollama),
    ("Exit", None),
]


def main():
    import argparse
    parser = argparse.ArgumentParser(description="AgentDispatch configurator")
    parser.add_argument("--user", action="store_true", help="Edit user config (~/.claude/dispatch.json)")
    args = parser.parse_args()

    project_root = _find_project_root()
    if args.user:
        config_path = Path.home() / ".claude" / "dispatch.json"
    else:
        config_path = project_root / ".claude" / "dispatch.json"

    if not config_path.exists():
        defaults = _load_json(DEFAULTS_PATH)
        _save_json(config_path, defaults)
        print(f"  Created default config: {config_path}")

    _print_header("AgentDispatch Configurator")
    print(f"  Config: {config_path}\n")

    while True:
        config = _load_json(config_path)

        print(f"\n{BOLD}Menu:{RESET}")
        for i, (label, _) in enumerate(MENU, 1):
            print(f"  {i}. {label}")

        choice = _input("\nChoice", "")
        if not choice:
            continue

        try:
            idx = int(choice)
            if idx == len(MENU):
                print(f"\n{DIM}Bye.{RESET}")
                break
            if 1 <= idx < len(MENU):
                _, action = MENU[idx - 1]
                action(config, config_path)
            else:
                print(f"  {RED}Invalid{RESET}")
        except ValueError:
            print(f"  {RED}Enter a number{RESET}")
        except KeyboardInterrupt:
            print(f"\n{DIM}Bye.{RESET}")
            break


if __name__ == "__main__":
    main()
