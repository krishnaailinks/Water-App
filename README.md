# Maruti Water

Flutter catalogue and dealer application for Maruti Water RO, backed by
Supabase. Android is the only shipping platform; there is no iOS or web target
in this repository.

- Application id: `com.krishnaailinks.marutiwater` (`.dev` for the dev flavour)
- Flutter 3.50 / Dart 3.14, `minSdk` 24, `compileSdk`/`targetSdk` 36

## One-time setup

```bash
flutter pub get
cp config/dev.json.example  config/dev.json
cp config/prod.json.example config/prod.json   # fill in the Supabase project
cp android/key.properties.example android/key.properties
```

Two separate switches decide what a build is, and they are not linked by the
toolchain: `--flavor` picks the application id and app name, while
`--dart-define-from-file` picks the Supabase project. `Env.isFlavorConsistent`
compares them at startup and refuses to run a build whose halves disagree.
`config/README.md` has the detail.

### Toolchain

The Android build needs **JDK 21 or newer**. AGP 9's lint calls Java 21 APIs
and crashes on JDK 17 part-way through a release build. Android Studio's
bundled runtime is a fine choice:

```bash
flutter config --jdk-dir="C:\Program Files\Android\Android Studio\jbr"
```

Also required in the Android SDK, and not installed by `flutter doctor`:
platform **android-36** and **NDK 28.2.13676358** (AGP 9.3.1's default; it is
resolved even though nothing here compiles native code). The SDK's `android
sdk install` writes package names with a `;` that its own parser rejects, so
if it reports `Package ndk not found`, fetch the archives from
`dl.google.com/android/repository` and unzip them into `platforms/android-36`
and `ndk/28.2.13676358` by hand.

`android/gradle.properties` sizes the Gradle and Kotlin daemons for a small
machine. The Flutter template's default of `-Xmx8G` with a 4G metaspace
exceeds physical memory on anything under 16 GB, and the daemon does not
report that honestly: it surfaces as phantom filesystem errors
(`Couldn't create directory`, `is not a directory`) against directories that
exist and are writable.

### Signing

`android/upload-keystore.jks` holds the upload key. `android/key.properties`
names it and carries its passwords; both files are git-ignored.

**Back the keystore up somewhere outside this machine.** Google Play ties the
listing to the first upload key it sees. Losing it means contacting Play
support to reset it, and losing it without a backup can mean publishing under a
new application id — a new listing, with none of the installs.

With no `key.properties` present the release build still completes, signed with
the local debug key, and prints a warning. That output is usable for testing on
a phone and is rejected by Play.

To regenerate the keystore from scratch:

```bash
keytool -genkey -v -keystore android/upload-keystore.jks -keyalg RSA -keysize 2048 -validity 10000 -alias upload
```

## Running on a phone

1. Enable **Developer options** and **USB debugging** on the device
   (Settings › About phone › tap Build number seven times).
2. Connect it by USB and accept the *Allow USB debugging?* prompt. Until that
   prompt is accepted `flutter devices` reports the device as
   `not authorized` and will not install anything.
3. Confirm it is visible, then run:

```bash
flutter devices
```

```bash
flutter run --flavor dev --dart-define-from-file=config/dev.json
```

Hot reload with `r`, hot restart with `R`, quit with `q`. Add `--release` to
check performance or anything that behaves differently under R8; debug builds
of a Flutter app are substantially slower and that is expected.

Wireless debugging, after one USB pairing, avoids the cable:

```bash
adb tcpip 5555
```

```bash
adb connect <phone-ip>:5555
```

## Release build

Bump `version:` in `pubspec.yaml` first — the part after `+` is the Android
`versionCode`, and Play rejects any upload whose `versionCode` it has already
seen. `1.0.0+1` becomes `1.0.1+2`, and so on.

App bundle, the format Play requires:

```bash
flutter build appbundle --release --flavor prod --dart-define-from-file=config/prod.json
```

Output: `build/app/outputs/bundle/prodRelease/app-prod-release.aab`

A universal APK, for installing directly on a phone without Play:

```bash
flutter build apk --release --flavor prod --dart-define-from-file=config/prod.json
```

Output: `build/app/outputs/flutter-apk/app-prod-release.apk`

Release builds run R8 with `isMinifyEnabled` and `isShrinkResources` on, so
anything reached only by reflection needs a keep rule in
`android/app/proguard-rules.pro`.

## Publishing to Google Play

1. Pay the one-time Google Play developer registration fee and complete
   identity verification. Verification is a prerequisite for publishing, not
   just for payouts, and can take several days.
2. In Play Console, create the app with package name
   `com.krishnaailinks.marutiwater`. The package name is permanent.
3. Leave **Play App Signing** enabled (the default). The upload key signs what
   is uploaded; Google re-signs with the app signing key it holds.
4. Complete the sections Play blocks release on: store listing, screenshots and
   feature graphic, content rating questionnaire, target audience, data safety
   form, and a privacy policy URL.
5. Upload the `.aab` to **Internal testing** first and install it from Play on
   a real device. The internal track is the only cheap way to catch problems
   that only appear in a Play-signed, Play-delivered build.
6. Promote to production when it holds up.

### Data safety form

The app collects and transmits, through Supabase: account identity, dealer and
customer contact details, and product photographs taken in-app. Camera and
photo-library access are requested for product photography. The form must
describe all of it, and Play checks the answers against what the binary does.


// "SUPABASE_URL": "https://werwkbfyuwntaanlknje.supabase.co",
<!-- "SUPABASE_ANON_KEY": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6IndlcndrYmZ5dXdudGFhbmxrbmplIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODgwNzg4MDAsImV4cCI6MjEwMzY1NDgwMH0.n4u8Hr4J-_zEAZjQSxx96IL_DEILZmiIpBDwobkpFWg", -->