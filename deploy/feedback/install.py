"""Install the independent receiver on the owner's existing website host as root."""
import argparse
import hashlib
import os
import shutil
import subprocess
from pathlib import Path


def run(*args):
    subprocess.run(args, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-caddy-sha", required=True)
    args = parser.parse_args()
    config = Path("/etc/caddy/Caddyfile")
    original = config.read_bytes()
    if hashlib.sha256(original).hexdigest() != args.expected_caddy_sha:
        raise SystemExit("Caddy configuration changed; inspect it before deploying.")
    if b"/api/feedback" in original:
        raise SystemExit("Feedback route already exists; inspect before updating.")
    marker = b"    handle /api/* {"
    if original.count(marker) != 1:
        raise SystemExit("Unexpected existing website configuration.")
    addition = b"""    handle /api/feedback {
        request_body {
            max_size 20KB
        }
        reverse_proxy 127.0.0.1:18765
    }
"""
    candidate = config.with_name("Caddyfile.feedback-candidate")
    candidate.write_bytes(original.replace(marker, addition + marker))
    candidate.chmod(0o644)
    run("caddy", "validate", "--config", str(candidate), "--adapter", "caddyfile")
    backup = config.with_name("Caddyfile.before-feedback")
    with backup.open("xb") as output:
        output.write(original)
    source = Path(__file__).resolve().parent
    target = Path("/opt/stu-mcp-feedback")
    target.mkdir(mode=0o755, exist_ok=True)
    shutil.copyfile(source / "receiver.py", target / "receiver.py")
    (target / "receiver.py").chmod(0o644)
    shutil.copyfile(source / "stu-mcp-feedback.service", "/etc/systemd/system/stu-mcp-feedback.service")
    run("systemctl", "daemon-reload")
    run("systemctl", "enable", "--now", "stu-mcp-feedback")
    run("systemctl", "is-active", "--quiet", "stu-mcp-feedback")
    # Preserve any concurrent configuration changes rather than overwrite them.
    if config.read_bytes() != original:
        raise SystemExit("Caddy changed during install; receiver installed, route not enabled.")
    os.replace(candidate, config)
    try:
        run("systemctl", "reload", "caddy")
    except subprocess.CalledProcessError:
        config.write_bytes(original)
        run("systemctl", "reload", "caddy")
        raise
    print("Installed receiver and public feedback route; prior Caddy configuration retained.")


if __name__ == "__main__":
    main()
