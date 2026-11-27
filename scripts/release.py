#!/usr/bin/env python3
"""Build a production release bundle for the Play Store, and prove it is the
one you meant to ship before you upload it.

    python scripts/release.py                 # build at the current version
    python scripts/release.py --bump build    # 1.0.1+2 -> 1.0.1+3, then build
    python scripts/release.py --bump patch     # 1.0.1+2 -> 1.0.2+3, then build
    python scripts/release.py --check          # preflight only, build nothing

What this exists to prevent, because each of these has actually bitten this
project:

* A release signed with DEBUG keys. If android/app/<keystore> is missing,
  Gradle prints one warning and signs with the debug key anyway -- the build
  still says SUCCESSFUL, and Play rejects the upload. This refuses to build
  unless the real keystore is present.

* A bundle built WITHOUT --dart-define-from-file. That produces an app that
  boots straight into the "missing configuration" screen, and nothing about
  the build looks wrong. The build always passes the config, and afterwards
  this reads the Supabase URL back out of the compiled binary to prove it
  landed.

* The version constants drifting apart. pubspec.yaml feeds the Android
  version; AppConfig.appVersion feeds Sentry. They have shipped out of sync
  before, filing crashes under a version that was never released. --bump
  moves both, and the build is refused if they disagree.

* Shipping the wrong Supabase project. config/prod.json has pointed at two
  different projects; the preflight prints which one this build will embed so
  you can stop before, not after.

This NEVER uploads anything. The last thing it prints is the path to the .aab
and what to do with it.

Verification needs Android build-tools (aapt2), found via ANDROID_HOME /
ANDROID_SDK_ROOT or the usual per-OS SDK location. If none is found the build
still runs; only the deep verification is skipped, and that is said plainly.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PUBSPEC = REPO / "pubspec.yaml"
APPCONFIG = REPO / "lib" / "core" / "config" / "app_config.dart"
PROD_CONFIG = REPO / "config" / "prod.json"
AAB = REPO / "build" / "app" / "outputs" / "bundle" / "prodRelease" / "app-prod-release.aab"

# The +N build number is optional in a Flutter version; when it is absent
# Flutter defaults versionCode to 1, which Play rejects on any upload after the
# first. The script tolerates its absence and warns.
VERSION_RE = re.compile(r"^version:\s*(\d+)\.(\d+)\.(\d+)(?:\+(\d+))?\s*$", re.M)
APPVER_RE = re.compile(r"appVersion\s*=\s*'([^']+)'")


def die(msg: str) -> None:
    sys.exit(f"\nrelease: {msg}")


def flutter(args: list[str]) -> list[str]:
    """Resolve the flutter launcher. On Windows it is flutter.bat, which
    Python's subprocess cannot CreateProcess directly, so it is run through
    cmd /c; elsewhere the resolved path is invoked straight."""
    exe = shutil.which("flutter")
    if not exe:
        die("flutter is not on PATH")
    return (["cmd", "/c", exe, *args] if os.name == "nt" else [exe, *args])


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=REPO, **kw)


# ---------------------------------------------------------------- version

def read_versions() -> tuple[str, str, bool]:
    m = VERSION_RE.search(PUBSPEC.read_text(encoding="utf-8"))
    if not m:
        die("pubspec.yaml has no 'version: X.Y.Z' line")
    has_build = m.group(4) is not None
    pub = f"{m.group(1)}.{m.group(2)}.{m.group(3)}" + (f"+{m.group(4)}" if has_build else "")
    am = APPVER_RE.search(APPCONFIG.read_text(encoding="utf-8"))
    if not am:
        die("could not find AppConfig.appVersion")
    return pub, am.group(1), has_build


def bump(current: str, kind: str) -> str:
    m = re.match(r"(\d+)\.(\d+)\.(\d+)(?:\+(\d+))?", current)
    major, minor, patch = (int(x) for x in m.groups()[:3])
    build = int(m.group(4)) if m.group(4) else 0
    if kind == "build":
        build += 1
    elif kind == "patch":
        patch, build = patch + 1, build + 1
    elif kind == "minor":
        minor, patch, build = minor + 1, 0, build + 1
    elif kind == "major":
        major, minor, patch, build = major + 1, 0, 0, build + 1
    return f"{major}.{minor}.{patch}+{build}"


def write_versions(new: str) -> None:
    PUBSPEC.write_text(
        VERSION_RE.sub(f"version: {new}", PUBSPEC.read_text(encoding="utf-8"), count=1),
        encoding="utf-8")
    APPCONFIG.write_text(
        APPVER_RE.sub(f"appVersion = '{new}'", APPCONFIG.read_text(encoding="utf-8"), count=1),
        encoding="utf-8")
    print(f"  version set to {new} in pubspec.yaml and app_config.dart")


# ---------------------------------------------------------------- preflight

def find_aapt2() -> Path | None:
    roots = [os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT")]
    roots += [
        Path.home() / "AppData/Local/Android/Sdk",   # Windows
        Path.home() / "Library/Android/sdk",          # macOS
        Path.home() / "Android/Sdk",                  # Linux
    ]
    for root in roots:
        if not root:
            continue
        bt = Path(root) / "build-tools"
        if bt.is_dir():
            for ver in sorted(bt.iterdir(), reverse=True):
                for name in ("aapt2.exe", "aapt2"):
                    if (ver / name).exists():
                        return ver / name
    return None


def preflight() -> tuple[str, str]:
    print("preflight")

    if not PROD_CONFIG.is_file():
        die(f"{PROD_CONFIG.relative_to(REPO)} is missing -- the build would ship "
            "with no Supabase config. It is git-ignored; restore it first.")
    cfg = json.loads(PROD_CONFIG.read_text(encoding="utf-8"))
    url = cfg.get("SUPABASE_URL", "")
    if cfg.get("APP_FLAVOR") != "prod":
        die(f"config/prod.json has APP_FLAVOR={cfg.get('APP_FLAVOR')!r}, not 'prod'. "
            "Env.isFlavorConsistent would send the app to the config-error screen.")
    print(f"  Supabase project:  {url}")
    print(f"  anon key:          {'publishable' if cfg.get('SUPABASE_ANON_KEY','').startswith('sb_') else 'legacy JWT'}")

    # The real keystore, not the debug fallback. Mirror the resolution in
    # android/app/build.gradle.kts: file() relative to android/app, and
    # rootProject.file() relative to android/.
    props = REPO / "android" / "key.properties"
    if not props.is_file():
        die("android/key.properties is missing. Gradle would sign with DEBUG "
            "keys and Play would reject the upload. Add it before releasing.")
    store = None
    for line in props.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("storeFile="):
            store = line.split("=", 1)[1].strip()
    if not store:
        die("android/key.properties has no storeFile=")
    candidates = [REPO / "android" / "app" / store, REPO / "android" / store]
    if not any(c.exists() for c in candidates):
        die(f"keystore '{store}' not found next to the app or under android/. "
            "Gradle would fall back to DEBUG signing. Put the keystore in place.")
    print(f"  signing keystore:  {store} (present)")

    pub, app, has_build = read_versions()
    if pub != app:
        die(f"version mismatch: pubspec.yaml {pub} vs AppConfig.appVersion {app}. "
            "Run with --bump, or set them equal, so Sentry files crashes under "
            "the shipped version.")
    print(f"  version:           {pub}")
    if not has_build:
        print("  WARNING: no +build number, so Android versionCode defaults to 1. "
              "Play accepts versionCode 1 only once; run --bump build to add one "
              "before any later upload.")
    return pub, url


# ---------------------------------------------------------------- verify

def verify_bundle(expected_version: str, expected_url: str) -> bool:
    if not AAB.is_file():
        die(f"expected a bundle at {AAB.relative_to(REPO)} but it is not there")
    print(f"\nverifying {AAB.relative_to(REPO)}  ({AAB.stat().st_size/1024/1024:.1f} MB)")

    aapt2 = find_aapt2()
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(AAB) as z:
            want = ["base/manifest/AndroidManifest.xml", "base/lib/arm64-v8a/libapp.so"]
            names = set(z.namelist())
            for w in want:
                if w in names:
                    z.extract(w, tmp)
        manifest = Path(tmp) / "base/manifest/AndroidManifest.xml"
        libapp = Path(tmp) / "base/lib/arm64-v8a/libapp.so"

        ok = True

        # Supabase URL compiled into the Dart snapshot.
        if libapp.exists():
            urls = sorted(set(re.findall(rb"https://[a-z0-9]+\.supabase\.co",
                                         libapp.read_bytes())))
            urls = [u.decode() for u in urls]
            if urls == [expected_url]:
                print(f"  supabase URL:   {expected_url}  OK")
            else:
                print(f"  supabase URL:   FAIL -- found {urls or 'none'}, "
                      f"expected {expected_url}")
                ok = False
        else:
            print("  supabase URL:   skipped (no arm64 libapp.so in bundle)")

        # Version + permissions from the protobuf manifest.
        if manifest.exists():
            raw = manifest.read_bytes()
            # The versionName is stored as a length-prefixed string right after
            # the "versionName" attribute key; match the whole X.Y.Z+N value
            # rather than reaching across the prefix bytes, which a greedy skip
            # would clip the leading digit off.
            vn = re.search(rb"versionName[^0-9]{0,8}(\d+\.\d+\.\d+\+\d+)", raw)
            name = vn.group(1).decode() if vn else "?"
            if name == expected_version:
                print(f"  versionName:    {name}  OK")
            else:
                print(f"  versionName:    FAIL -- bundle says {name}, "
                      f"expected {expected_version}")
                ok = False

            perms = sorted(set(re.findall(rb"android\.permission\.[A-Z_]+", raw)))
            perms = [p.decode().rsplit(".", 1)[1] for p in perms]
            app_perms = [p for p in perms if p in
                         ("CAMERA", "INTERNET", "ACCESS_NETWORK_STATE")]
            media = [p for p in perms if "MEDIA" in p or "EXTERNAL_STORAGE" in p]
            print(f"  permissions:    {', '.join(app_perms)}")
            if media:
                print(f"  media perms:    WARNING -- {', '.join(media)} present; "
                      "Play will demand a Photo/Video declaration")
        else:
            print("  version/perms:  skipped (no manifest extracted)")

        if not aapt2:
            print("  (aapt2 not found; used a direct scan of the bundle instead)")

    return ok


# ---------------------------------------------------------------- main

def main() -> int:
    p = argparse.ArgumentParser(
        description="Build and verify a production release bundle.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bump", choices=("build", "patch", "minor", "major"),
                   help="raise the version in pubspec.yaml and AppConfig first")
    p.add_argument("--check", action="store_true",
                   help="run the preflight and exit; build nothing")
    p.add_argument("--no-clean", action="store_true",
                   help="skip 'flutter clean' (faster, slightly less reproducible)")
    args = p.parse_args()

    if not shutil.which("flutter"):
        die("flutter is not on PATH")

    version, url = preflight()
    if args.check:
        print("\npreflight OK. Nothing was built.")
        return 0

    if args.bump:
        version = bump(version, args.bump)
        print(f"\nbumping ({args.bump}) -> {version}")
        write_versions(version)
        r = run(flutter(["test", "test/app_version_test.dart"]))
        if r.returncode != 0:
            die("the version-sync test failed after the bump; not building")

    # build.gradle.kts sets versionName = "<flutter.versionName>+<versionCode>",
    # and versionCode defaults to 1 when pubspec has no +N. So the manifest
    # always carries base+code, which is what verify_bundle must expect.
    base, _, build = re.match(r"(\d+\.\d+\.\d+)(\+(\d+))?", version).groups()
    manifest_version = f"{base}+{build or '1'}"

    print("\nbuilding")
    if not args.no_clean:
        run(flutter(["clean"]))
    if run(flutter(["pub", "get"])).returncode != 0:
        die("flutter pub get failed")

    build = run(flutter(["build", "appbundle",
                         "--flavor", "prod",
                         "--dart-define-from-file=config/prod.json"]),
                capture_output=True, text=True)
    sys.stdout.write(build.stdout[-2000:] if build.stdout else "")
    if build.returncode != 0:
        sys.stderr.write(build.stderr[-2000:] if build.stderr else "")
        die("flutter build failed")

    # Gradle's silent debug-key fallback prints this and keeps going.
    if "cannot be published" in (build.stdout + build.stderr):
        die("Gradle signed with DEBUG keys (keystore was not found at build "
            "time). The bundle is not publishable. Fix android/key.properties.")

    if not verify_bundle(manifest_version, url):
        die("the built bundle failed verification -- do NOT upload it")

    print(f"\nrelease {version} ready:")
    print(f"  {AAB}")
    print("\nnext:")
    print("  1. Play Console > Production (or Internal testing) > Create new release")
    print("  2. Upload the .aab above")
    print("  3. Reviewers need working credentials under")
    print("     Policy > App content > App access (the app cannot be used signed out)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
