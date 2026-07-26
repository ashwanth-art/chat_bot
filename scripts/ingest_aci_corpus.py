"""Upload the bundled ACI public-site corpus to the chatbot knowledge base."""

import os
import time
from pathlib import Path

import httpx

API_URL = os.getenv("CHATBOT_BASE_URL", "http://localhost:8000").rstrip("/")
API_KEY = os.environ["CHATBOT_API_KEY"]
TENANT_ID = os.getenv("ACI_TENANT_ID", "aci-infotech")
CORPUS_DIR = Path(__file__).resolve().parents[1] / "sample_data" / "aci"


def main() -> None:
    documents = sorted(CORPUS_DIR.glob("*.md"))
    if not documents:
        raise SystemExit(f"No Markdown documents found in {CORPUS_DIR}")

    headers = {"Authorization": f"Bearer {API_KEY}"}
    with httpx.Client(timeout=180) as client:
        for document in documents:
            content = document.read_bytes()
            response = None
            for attempt in range(6):
                response = client.post(
                    f"{API_URL}/v1/documents",
                    params={"tenant_id": TENANT_ID},
                    headers=headers,
                    files={"file": (document.name, content, "text/markdown")},
                )
                if response.status_code not in {404, 429} and response.status_code < 500:
                    break
                if attempt < 5:
                    wait_seconds = min(2 ** (attempt + 1), 15)
                    print(
                        f"{document.name}: transient HTTP {response.status_code}; "
                        f"retrying in {wait_seconds}s"
                    )
                    time.sleep(wait_seconds)
            assert response is not None
            response.raise_for_status()
            result = response.json()
            print(f"{result['document']}: {result['chunks']} chunks indexed")

    print(f"Indexed {len(documents)} ACI documents for tenant '{TENANT_ID}'.")


if __name__ == "__main__":
    main()
