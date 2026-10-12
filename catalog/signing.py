"""Sign the store API, so a console can trust the catalog without trusting the web host.

The build writes `api/v1/manifest.json`: the SHA-256 of every JSON file of the
API, and the catalog's sequence number. The deploy then signs that one file
with an Ed25519 key and writes the raw 64-byte signature next to it as
`manifest.sig`. A client verifies the signature with a public key it carries,
refuses a sequence lower than one it has already accepted, and checks every
API file it downloads against the manifest (docs/api.md).

The private key is a deployment secret (`CATALOG_SIGNING_KEY`, a PEM); it is
never in the repository. The public keys are, under `keys/`: the one the
deploy signs with and a spare whose private half is kept offline. Signing uses
the `openssl` program, so the catalog needs no cryptography package. The keys
have no expiry.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEYS = ROOT / "keys"
MANIFEST = "manifest.json"
SIGNATURE = "manifest.sig"
# Signed by itself and never listed in the manifest (catalog/news.py).
NEWS = "news.json"
NEWS_SIGNATURE = "news.sig"
SIGNATURE_BYTES = 64


class SigningError(RuntimeError):
    pass


def raw_public_key(pem: str) -> bytes:
    """The 32 key bytes of an Ed25519 public key in PEM form (the end of its DER encoding)."""
    der = base64.b64decode("".join(line for line in pem.splitlines() if line and not line.startswith("-----")))
    if len(der) != 44:
        raise SigningError("not an Ed25519 public key")
    return der[-32:]


def key_id(raw: bytes) -> str:
    """A short public name for a key: the start of the SHA-256 of its 32 bytes."""
    return hashlib.sha256(raw).hexdigest()[:16]


def public_keys(directory: Path = KEYS) -> dict[str, Path]:
    """Key ID to PEM file, for every public key the catalog publishes."""
    return {key_id(raw_public_key(path.read_text(encoding="utf-8"))): path
            for path in sorted(directory.glob("*.pub.pem"))}


def write_manifest(api_root: Path, schema: int, sequence: int, commit: str) -> Path:
    """List every JSON file of the API with its hash. Deterministic for a given set of files."""
    files = {path.relative_to(api_root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in sorted(api_root.rglob("*.json")) if path.name not in (MANIFEST, NEWS)}
    manifest = api_root / MANIFEST
    manifest.write_text(json.dumps({"schema": schema, "sequence": sequence, "commit": commit, "files": files},
                                   ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n", encoding="utf-8")
    (api_root / SIGNATURE).unlink(missing_ok=True)
    (api_root / NEWS_SIGNATURE).unlink(missing_ok=True)
    return manifest


def _openssl(*args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["openssl", *args], capture_output=True, check=False)
    except OSError as error:
        raise SigningError(f"openssl is not available: {error}") from error


def verify(manifest: Path, signature: Path, public_pem: Path) -> bool:
    result = _openssl("pkeyutl", "-verify", "-pubin", "-inkey", str(public_pem), "-rawin",
                      "-in", str(manifest), "-sigfile", str(signature))
    return result.returncode == 0


def sign(api_root: Path, private_pem: str, keys_dir: Path = KEYS) -> str:
    """Sign the manifest and return the ID of the published key that verifies it.

    Nothing about the key is ever printed. The signature is kept only if one of
    the published public keys verifies it, so a wrong secret can't deploy a
    catalog that clients would reject.
    """
    manifest, signature = api_root / MANIFEST, api_root / SIGNATURE
    if not manifest.is_file():
        raise SigningError(f"{manifest} is missing; build the site first")
    if json.loads(manifest.read_text(encoding="utf-8")).get("sequence", 0) < 1:
        raise SigningError("the manifest has no sequence number (the build couldn't read the git history)")
    with tempfile.TemporaryDirectory(prefix="catalog-sign-") as tmp:
        key = Path(tmp) / "key.pem"
        key.touch(mode=0o600)
        key.write_text(private_pem if private_pem.endswith("\n") else private_pem + "\n", encoding="utf-8")
        result = _openssl("pkeyutl", "-sign", "-inkey", str(key), "-rawin", "-in", str(manifest), "-out", str(signature))
        # The news, when the build wrote any, with the same key.
        news, news_signature = api_root / NEWS, api_root / NEWS_SIGNATURE
        news_signature.unlink(missing_ok=True)
        if result.returncode == 0 and news.is_file():
            signed = _openssl("pkeyutl", "-sign", "-inkey", str(key), "-rawin", "-in", str(news),
                              "-out", str(news_signature))
            if signed.returncode != 0 or not news_signature.is_file() or \
                    news_signature.stat().st_size != SIGNATURE_BYTES:
                news_signature.unlink(missing_ok=True)
                signature.unlink(missing_ok=True)
                raise SigningError("openssl could not sign the news")
    if result.returncode != 0 or not signature.is_file() or signature.stat().st_size != SIGNATURE_BYTES:
        signature.unlink(missing_ok=True)
        news_signature.unlink(missing_ok=True)
        raise SigningError("openssl could not sign the manifest; is the signing key an Ed25519 private key in PEM form?")
    for identifier, public in public_keys(keys_dir).items():
        if verify(manifest, signature, public) and (not news_signature.is_file() or
                                                    verify(news, news_signature, public)):
            return identifier
    signature.unlink(missing_ok=True)
    news_signature.unlink(missing_ok=True)
    raise SigningError("the signing key is not one of the published public keys in keys/")


def signing_key_from_environment() -> str | None:
    value = os.environ.get("CATALOG_SIGNING_KEY", "").strip()
    return value or None
