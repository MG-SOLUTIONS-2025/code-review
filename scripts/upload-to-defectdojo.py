"""Upload scan results to DefectDojo."""

import argparse
import os
import sys
import time

import requests

MAX_UPLOAD_SIZE_MB = 50


def upload_scan(
    file_path: str,
    scan_type: str,
    engagement_id: str,
    defectdojo_url: str,
    api_token: str,
) -> bool:
    from urllib.parse import urljoin

    base = defectdojo_url.rstrip("/") + "/"
    url = urljoin(base, "api/v2/import-scan/")

    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    if file_size_mb > MAX_UPLOAD_SIZE_MB:
        print(
            f"Error: {file_path} is {file_size_mb:.1f} MB, exceeds {MAX_UPLOAD_SIZE_MB} MB limit",
            file=sys.stderr,
        )
        return False

    headers = {"Authorization": f"Token {api_token}"}
    data = {
        "scan_type": scan_type,
        "engagement": engagement_id,
        "minimum_severity": "Info",
        "active": "true",
        "verified": "false",
    }

    last_exc = None
    for attempt in range(1, 4):
        try:
            with open(file_path, "rb") as f:
                resp = requests.post(url, headers=headers, data=data, files={"file": f})
            if resp.status_code in (200, 201):
                print(f"Uploaded {file_path} ({scan_type}): HTTP {resp.status_code}")
                return True
            print(
                f"Failed to upload {file_path}: HTTP {resp.status_code} - {resp.text}",
                file=sys.stderr,
            )
            return False
        except requests.exceptions.ConnectionError as e:
            print(f"Upload connection error on attempt {attempt}/3: {e}", file=sys.stderr)
            last_exc = e
        except requests.exceptions.Timeout as e:
            print(f"Upload timeout on attempt {attempt}/3: {e}", file=sys.stderr)
            last_exc = e
        if attempt < 3:
            time.sleep(2 ** attempt)

    print(f"Upload failed after 3 attempts: {last_exc}", file=sys.stderr)
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload scan results to DefectDojo")
    parser.add_argument("--file", required=True, help="Path to scan report file")
    parser.add_argument(
        "--scan-type",
        required=True,
        help='Scan type (e.g. "Semgrep JSON Report", "Gitleaks Scan", "Trivy Scan")',
    )
    parser.add_argument(
        "--engagement-id", required=True, help="DefectDojo engagement ID"
    )
    parser.add_argument("--url", default=None, help="DefectDojo URL")
    parser.add_argument("--token", default=None, help="DefectDojo API token")
    args = parser.parse_args()

    defectdojo_url = args.url or os.environ.get("DEFECTDOJO_URL", "")
    api_token = args.token or os.environ.get("DEFECTDOJO_API_TOKEN", "")

    if not defectdojo_url:
        print("Error: DefectDojo URL required (--url or DEFECTDOJO_URL env)", file=sys.stderr)
        sys.exit(1)
    if not api_token:
        print("Error: API token required (--token or DEFECTDOJO_API_TOKEN env)", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(args.file):
        print(f"Error: File not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    success = upload_scan(args.file, args.scan_type, args.engagement_id, defectdojo_url, api_token)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
