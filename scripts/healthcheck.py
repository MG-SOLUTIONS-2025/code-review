"""Check health of all services in the code review stack."""

import os
import sys

import requests

SERVICES = {
    "Ollama": {
        "url": os.environ.get("OLLAMA_URL", "http://localhost:11434") + "/api/tags",
    },
    "DefectDojo": {
        "url": os.environ.get("DEFECTDOJO_URL", "http://localhost:8080") + "/api/v2/",
    },
    "API Gateway": {
        "url": os.environ.get("API_GATEWAY_URL", "http://localhost:8000") + "/api/health",
    },
    "Dashboard": {
        "url": os.environ.get("DASHBOARD_URL", "http://localhost:5173") + "/",
    },
    "PR-Agent": {
        "url": os.environ.get("PR_AGENT_URL", "http://localhost:3000") + "/",
    },
}


def check_service(name: str, url: str) -> bool:
    try:
        resp = requests.get(url, timeout=5)
        ok = resp.status_code < 500
        status = f"OK ({resp.status_code})" if ok else f"FAIL ({resp.status_code})"
        print(f"  {name:15s} {status:15s} {url}")
        return ok
    except requests.exceptions.ConnectionError:
        print(f"  {name:15s} {'UNREACHABLE':15s} {url}")
        return False
    except requests.exceptions.Timeout:
        print(f"  {name:15s} {'TIMEOUT':15s} {url}")
        return False


def main() -> None:
    print("Service Health Check")
    print("=" * 60)

    all_ok = True
    for name, cfg in SERVICES.items():
        if not check_service(name, cfg["url"]):
            all_ok = False

    print("=" * 60)
    if all_ok:
        print("All services healthy.")
    else:
        print("Some services are unhealthy.")
        sys.exit(1)


if __name__ == "__main__":
    main()
