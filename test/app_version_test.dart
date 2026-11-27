import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:maruti_water/core/config/app_config.dart';

/// The guard AppConfig.appVersion's doc comment has always claimed.
///
/// It did not exist, and the constant had drifted to 0.1.0+3 while pubspec.yaml
/// said 1.0.0+1 -- so every crash Sentry received was tagged with a release
/// that had not shipped in months. Reading the version at runtime with
/// package_info_plus would remove the duplication altogether, but Sentry is
/// configured before the first frame and a whole dependency to avoid one
/// constant is a poor trade. Comparing the two in a test is enough.
void main() {
  test('AppConfig.appVersion matches version: in pubspec.yaml', () {
    final pubspec = File('pubspec.yaml').readAsStringSync();
    final match = RegExp(r'^version:\s*(\S+)\s*$', multiLine: true)
        .firstMatch(pubspec);

    expect(match, isNotNull, reason: 'pubspec.yaml has no version: line');

    expect(
      AppConfig.appVersion,
      match!.group(1),
      reason: 'AppConfig.appVersion and pubspec.yaml disagree. Change both, '
          'or Sentry files this build under the wrong release.',
    );
  });
}
