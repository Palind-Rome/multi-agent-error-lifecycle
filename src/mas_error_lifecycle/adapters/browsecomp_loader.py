"""BrowseComp dataset loader + decrypter (stdlib only).

The official BrowseComp release is an encrypted CSV. Each row carries a
``canary`` string that is the decryption password for that row's ``problem`` and
``answer``. The scheme is base64 + XOR with a SHA256-derived keystream, exactly
as in ``openai/simple-evals``' ``browsecomp_eval.py``.

This module downloads the CSV once, decrypts it, and caches a plain JSONL of
``{question, answer, source_row}``. It never writes the API key or any secret.
"""

from __future__ import annotations

import base64
import hashlib
import json
import urllib.error
import urllib.request
from pathlib import Path

DATASET_URL = (
    "https://openaipublic.blob.core.windows.net/simple-evals/browse_comp_test_set.csv"
)
DEFAULT_CACHE = Path("outputs/browsecomp-decrypted.jsonl")
_USER_AGENT = "mas-error-lifecycle/0.3 browsecomp-pilot"


class BrowseCompLoadError(RuntimeError):
    """Safe public error for a failed download/decrypt (no secrets)."""


def _derive_key(password: str, length: int) -> bytes:
    digest = hashlib.sha256(password.encode()).digest()
    return digest * (length // len(digest)) + digest[: length % len(digest)]


def decrypt(ciphertext_b64: str, password: str) -> str:
    """Decrypt one base64+XOR field using its row's canary as the password."""
    encrypted = base64.b64decode(ciphertext_b64)
    key = _derive_key(password, len(encrypted))
    return bytes(a ^ b for a, b in zip(encrypted, key)).decode()


def _download_csv(cache_dir: Path) -> str:
    request = urllib.request.Request(DATASET_URL, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=120.0) as response:
            return response.read().decode("utf-8")
    except (urllib.error.URLError, OSError) as exc:
        raise BrowseCompLoadError(f"download failed: {type(exc).__name__}") from exc


def _parse_csv(text: str) -> list[dict[str, str]]:
    import csv
    import io

    return list(csv.DictReader(io.StringIO(text)))


def load_browsecomp(cache_path: Path | None = None, *, refresh: bool = False) -> list[dict]:
    """Return decrypted ``[{question, answer, source_row}]``, caching to disk."""
    cache_path = cache_path or DEFAULT_CACHE
    cache_path = cache_path.resolve()
    if cache_path.is_file() and not refresh:
        return [json.loads(line) for line in cache_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    raw = _download_csv(cache_path.parent)
    rows = _parse_csv(raw)
    questions: list[dict] = []
    for index, row in enumerate(rows):
        canary = row.get("canary", "")
        try:
            problem = decrypt(row.get("problem", ""), canary)
            answer = decrypt(row.get("answer", ""), canary)
        except Exception as exc:  # noqa: BLE001
            raise BrowseCompLoadError(
                f"decrypt failed at row {index}: {type(exc).__name__}"
            ) from exc
        questions.append({"question": problem, "answer": answer, "source_row": index})

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        "\n".join(json.dumps(q, ensure_ascii=False) for q in questions) + "\n",
        encoding="utf-8",
    )
    return questions


if __name__ == "__main__":
    import sys

    data = load_browsecomp(refresh="--refresh" in sys.argv)
    print(f"loaded {len(data)} BrowseComp questions")
    if data:
        print("example Q:", data[0]["question"][:120])
        print("example A:", data[0]["answer"][:120])
