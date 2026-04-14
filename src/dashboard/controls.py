"""
Control operations for the dashboard — service management, git pull, manual cycles.

Safety:
- Only a fixed whitelist of services can be controlled
- All actions logged to logs/controls.log for audit
- systemctl operations require passwordless sudo config (see docs/CLOUD_DEPLOYMENT.md)
"""

import logging
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from src.config import LOGS_BASE, PROJECT_ROOT, load_settings
from src.logging_utils.deposits import get_capital_base, record_deposit

logger = logging.getLogger(__name__)

# Whitelist of services that can be controlled
ALLOWED_SERVICES = {"trading-agent-paper", "trading-agent-live"}
# Services that can be restarted but not stopped/started (dashboard manages itself)
SELF_RESTART_SERVICES = {"trading-dashboard"}

CONTROL_LOG = LOGS_BASE / "controls.log"

# In-memory cooldown for manual cycle triggers (seconds between real cycles)
_LAST_REAL_CYCLE: dict[str, datetime] = {}
REAL_CYCLE_COOLDOWN_SEC = 300


def _audit(action: str, target: str, result: str, details: str = ""):
    """Log a control action to the audit log."""
    CONTROL_LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now().isoformat()} {action} {target} {result}"
    if details:
        line += f" — {details}"
    with open(CONTROL_LOG, "a") as f:
        f.write(line + "\n")
    logger.info(line)


def _run(cmd: list[str], timeout: int = 30) -> tuple[int, str, str]:
    """Run a command safely, returning (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"Timeout after {timeout}s"
    except FileNotFoundError as e:
        return 127, "", str(e)
    except Exception as e:
        return 1, "", str(e)


def get_service_status(service: str) -> dict:
    """
    Get the status of a systemd service.

    Returns dict with: name, active (bool), status (str), uptime (str), memory
    """
    if service not in ALLOWED_SERVICES and service != "trading-dashboard":
        return {"name": service, "error": "service not in whitelist"}

    rc, stdout, stderr = _run(["systemctl", "is-active", service], timeout=5)
    active = stdout.strip() == "active"

    # Get detailed info
    rc2, show_out, _ = _run(
        [
            "systemctl", "show", service,
            "--property=ActiveState,SubState,ActiveEnterTimestamp,MainPID,MemoryCurrent",
            "--no-pager",
        ],
        timeout=5,
    )

    props = {}
    for line in show_out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            props[k] = v

    active_since = props.get("ActiveEnterTimestamp", "")
    uptime = ""
    if active_since and active_since != "0":
        try:
            since = datetime.strptime(active_since, "%a %Y-%m-%d %H:%M:%S %Z")
            delta = datetime.now() - since
            total_minutes = int(delta.total_seconds() / 60)
            if total_minutes < 60:
                uptime = f"{total_minutes}m"
            elif total_minutes < 1440:
                uptime = f"{total_minutes // 60}h {total_minutes % 60}m"
            else:
                days = total_minutes // 1440
                hours = (total_minutes % 1440) // 60
                uptime = f"{days}d {hours}h"
        except Exception:
            uptime = active_since[:16]

    mem_bytes = props.get("MemoryCurrent", "0")
    try:
        mem_mb = int(mem_bytes) / 1024 / 1024
        memory = f"{mem_mb:.1f} MB"
    except (ValueError, TypeError):
        memory = "—"

    return {
        "name": service,
        "active": active,
        "status": f"{props.get('ActiveState', 'unknown')} ({props.get('SubState', '')})".strip(),
        "uptime": uptime,
        "memory": memory,
        "pid": props.get("MainPID", "—"),
    }


def restart_service(service: str) -> dict:
    """Restart a systemd service (requires passwordless sudo)."""
    if service in SELF_RESTART_SERVICES:
        # Deferred restart — fire off a background shell that waits 2 seconds
        # so this HTTP response can complete before the process is killed.
        try:
            subprocess.Popen(
                ["sh", "-c", f"sleep 2 && sudo systemctl restart {service}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            _audit("restart", service, "scheduled", "deferred 2s")
            return {
                "success": True,
                "message": f"{service} restart scheduled. Refresh in ~5 seconds.",
            }
        except Exception as e:
            _audit("restart", service, "failed", str(e))
            return {"success": False, "message": f"Failed: {e}"}

    if service not in ALLOWED_SERVICES:
        _audit("restart", service, "rejected", "not in whitelist")
        return {"success": False, "message": "Service not in whitelist"}

    rc, stdout, stderr = _run(["sudo", "systemctl", "restart", service], timeout=30)
    if rc == 0:
        _audit("restart", service, "ok")
        return {"success": True, "message": f"Restarted {service}"}
    else:
        _audit("restart", service, "failed", stderr.strip())
        return {"success": False, "message": f"Failed: {stderr.strip()}"}


def start_service(service: str) -> dict:
    """Start a systemd service."""
    if service not in ALLOWED_SERVICES:
        _audit("start", service, "rejected", "not in whitelist")
        return {"success": False, "message": "Service not in whitelist"}

    rc, stdout, stderr = _run(["sudo", "systemctl", "start", service], timeout=30)
    if rc == 0:
        _audit("start", service, "ok")
        return {"success": True, "message": f"Started {service}"}
    else:
        _audit("start", service, "failed", stderr.strip())
        return {"success": False, "message": f"Failed: {stderr.strip()}"}


def stop_service(service: str) -> dict:
    """Stop a systemd service."""
    if service not in ALLOWED_SERVICES:
        _audit("stop", service, "rejected", "not in whitelist")
        return {"success": False, "message": "Service not in whitelist"}

    rc, stdout, stderr = _run(["sudo", "systemctl", "stop", service], timeout=30)
    if rc == 0:
        _audit("stop", service, "ok")
        return {"success": True, "message": f"Stopped {service}"}
    else:
        _audit("stop", service, "failed", stderr.strip())
        return {"success": False, "message": f"Failed: {stderr.strip()}"}


def get_logs(service: str, lines: int = 50) -> str:
    """Get recent log output from a systemd service."""
    if service not in ALLOWED_SERVICES and service != "trading-dashboard":
        return "Service not in whitelist"

    rc, stdout, stderr = _run(
        [
            "journalctl",
            "-u", service,
            "-n", str(lines),
            "--no-pager",
            "--output=cat",
        ],
        timeout=10,
    )
    if rc != 0:
        return f"Error: {stderr}"
    return stdout or "(no recent logs)"


def git_pull() -> dict:
    """Pull latest code from GitHub."""
    rc, stdout, stderr = _run(
        ["git", "-C", str(PROJECT_ROOT), "pull", "--ff-only"],
        timeout=30,
    )
    if rc == 0:
        _audit("git_pull", "main", "ok")
        return {"success": True, "message": stdout.strip() or "Already up to date"}
    else:
        _audit("git_pull", "main", "failed", stderr.strip())
        return {"success": False, "message": f"Failed: {stderr.strip()}"}


def refresh_dependencies() -> dict:
    """Reinstall Python dependencies (pip install -e .)."""
    python = shutil.which("python3.11") or shutil.which("python3") or "python"
    rc, stdout, stderr = _run(
        [python, "-m", "pip", "install", "--user", "-e", str(PROJECT_ROOT)],
        timeout=300,
    )
    if rc == 0:
        _audit("pip_install", "deps", "ok")
        # Return the last few lines to keep the response small
        tail = "\n".join(stdout.splitlines()[-5:])
        return {"success": True, "message": tail or "Dependencies refreshed"}
    else:
        _audit("pip_install", "deps", "failed", stderr.strip()[:200])
        return {"success": False, "message": f"Failed: {stderr.strip()[:500]}"}


def trigger_manual_cycle(mode: str, dry_run: bool = True) -> dict:
    """
    Trigger a manual analysis cycle in the background.
    Defaults to dry-run for safety; set dry_run=False for a real cycle.
    Real cycles are rate-limited per mode (REAL_CYCLE_COOLDOWN_SEC).
    """
    if mode not in ("paper", "live"):
        return {"success": False, "message": "Invalid mode"}

    if not dry_run:
        last = _LAST_REAL_CYCLE.get(mode)
        if last is not None:
            elapsed = (datetime.now() - last).total_seconds()
            if elapsed < REAL_CYCLE_COOLDOWN_SEC:
                wait = int(REAL_CYCLE_COOLDOWN_SEC - elapsed)
                _audit("manual_cycle", mode, "rate_limited", f"wait {wait}s")
                return {
                    "success": False,
                    "message": f"Cooldown: wait {wait}s before triggering another real {mode} cycle.",
                }

    env_file = f".env.{mode}"
    python = shutil.which("python3.11") or shutil.which("python3") or "python"

    cmd = [python, "-m", "src.agent.orchestrator", "--env", env_file]
    if dry_run:
        cmd.append("--dry-run")

    try:
        # Spawn in background, don't wait for it
        subprocess.Popen(
            cmd,
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={"PATH": "/usr/bin:/usr/local/bin", "SKIP_LIVE_CONFIRM": "true", "HOME": "/home/ec2-user"},
            start_new_session=True,
        )
        if not dry_run:
            _LAST_REAL_CYCLE[mode] = datetime.now()
        _audit("manual_cycle", mode, "started", "dry_run" if dry_run else "LIVE")
        label = "dry-run" if dry_run else "LIVE"
        return {
            "success": True,
            "message": f"{label} cycle started in background. Check logs for output.",
        }
    except Exception as e:
        _audit("manual_cycle", mode, "failed", str(e))
        return {"success": False, "message": f"Failed: {e}"}


def submit_deposit(mode: str, amount: float, note: str = "") -> dict:
    """
    Record a cash deposit or withdrawal to the deposits log for the given mode.
    Positive = deposit, negative = withdrawal. Returns dict with success + new capital base.
    """
    if mode not in ("paper", "live"):
        _audit("deposit", mode, "rejected", "invalid mode")
        return {"success": False, "message": "Invalid mode"}

    if amount == 0 or amount is None:
        return {"success": False, "message": "Amount must be non-zero"}

    if abs(amount) > 1_000_000:
        _audit("deposit", mode, "rejected", f"amount {amount} exceeds sanity cap")
        return {"success": False, "message": "Amount exceeds $1,000,000 sanity cap"}

    try:
        entry = record_deposit(mode, amount, note)
        settings = load_settings(env_file=f".env.{mode}")
        new_base = get_capital_base(settings)
        _audit("deposit", mode, "ok", f"${amount:,.2f} — {note[:60]}")
        action = "Deposit" if amount >= 0 else "Withdrawal"
        return {
            "success": True,
            "message": f"{action} of ${abs(amount):,.2f} recorded. New capital base: ${new_base:,.2f}",
            "entry": entry,
            "new_base": new_base,
        }
    except Exception as e:
        _audit("deposit", mode, "failed", str(e))
        return {"success": False, "message": f"Failed: {e}"}


def get_server_health() -> dict:
    """Get basic server health info — uptime, disk, memory."""
    health = {}

    rc, stdout, _ = _run(["uptime"], timeout=5)
    if rc == 0:
        health["uptime"] = stdout.strip()

    rc, stdout, _ = _run(["df", "-h", "/"], timeout=5)
    if rc == 0:
        # Parse: Filesystem Size Used Avail Use% Mounted
        lines = stdout.splitlines()
        if len(lines) >= 2:
            parts = lines[1].split()
            if len(parts) >= 5:
                health["disk_used"] = parts[2]
                health["disk_avail"] = parts[3]
                health["disk_pct"] = parts[4]

    rc, stdout, _ = _run(["free", "-m"], timeout=5)
    if rc == 0:
        # Parse: Mem: total used free ...
        for line in stdout.splitlines():
            if line.startswith("Mem:"):
                parts = line.split()
                if len(parts) >= 4:
                    health["mem_total_mb"] = parts[1]
                    health["mem_used_mb"] = parts[2]
                    health["mem_free_mb"] = parts[3]
                break

    return health


def read_recent_audit(lines: int = 20) -> list[str]:
    """Read the most recent audit log entries."""
    if not CONTROL_LOG.exists():
        return []
    try:
        with open(CONTROL_LOG) as f:
            all_lines = f.readlines()
        return [line.strip() for line in all_lines[-lines:]]
    except Exception:
        return []
