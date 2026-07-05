# Changelog

## [1.0.2] - 2026-07-05

### Fixed
- Keep the list marker on the same line as its content when serializing node text in the extension reader.

## [1.0.1] - 2026-04-13

### Fixed
- Detect Homebrew-installed `ffmpeg` in packaged macOS launches, write the discovered path into app settings, and allow a custom app-level override when the binary is installed elsewhere.
- Report missing runtime dependencies when the app starts instead of failing later during synthesis or export.
- Show readable startup and synthesis error details in the desktop app and extension health UI.

## [1.0.0] - 2026-04-13

### Added
- Initial public release of Local Voice desktop and Chrome extension.
