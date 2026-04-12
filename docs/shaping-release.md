---
shaping: true
---

# Release Preparation — Local Voice

**Goal:** Ship v1.0 of the Mac desktop app and Chrome extension as a public product by Majestic Labs LLC.

---

## Requirements (R)

| ID | Requirement | Status |
|----|-------------|--------|
| R0 | Ship a downloadable Mac app and a Chrome extension that users can install | Core goal |
| R1 | All user-facing surfaces reference majesticlabs.dev and Majestic Labs LLC, Austin TX | Must-have |
| R2 | Mac app is code-signed and notarized so macOS Gatekeeper doesn't block it | 🟡 Nice-to-have (blocked — no Apple Developer account yet) |
| R3 | Chrome extension is published on Chrome Web Store | Must-have |
| R4 | Legal documents exist: MIT license, privacy policy, terms of service | Must-have |
| R5 | Versions are aligned and bumped to 1.0.0 across all components | Must-have |
| R6 | Product distributed via both GitHub Releases and majesticlabs.dev | Must-have |
| R7 | App metadata is complete (copyright, author, descriptions, icons) | Must-have |
| R8 | README and user-facing docs are release-quality | Must-have |

---

## Current State (Gaps)

| Area | Current | Gap |
|------|---------|-----|
| **Versions** | 0.1.0 everywhere except Cargo.toml (0.2.0) | Misaligned; need 1.0.0 |
| **Company branding** | Author: "David Paluy", no company refs | Need Majestic Labs LLC + majesticlabs.dev everywhere |
| **App identifier** | `dev.localvoice.desktop` | Change to `dev.majesticlabs.localvoice` |
| **License** | None | Need LICENSE file |
| **Privacy policy** | None | Required for Chrome Web Store and Apple notarization |
| **Terms of service** | None | Recommended for public release |
| **Code signing** | None configured | Required for Mac distribution without Gatekeeper warnings |
| **Chrome Web Store** | Not published | Need developer account, store listing assets |
| **Distribution** | Local build only | Need downloadable artifact or store listing |
| **Copyright strings** | Missing | Need in Cargo.toml, tauri.conf.json, manifest.json |
| **Extension description** | "...on this Mac." | Needs polish for store listing |

---

## Decisions

| # | Decision | Answer |
|---|----------|--------|
| 1 | License type | MIT (open source) |
| 2 | Apple Developer account | Don't have one yet — code signing deferred |
| 3 | Chrome Web Store account | Have personal account — can publish |
| 4 | Distribution channel | Both: GitHub Releases + majesticlabs.dev |
| 5 | App identifier | Rebrand to `dev.majesticlabs.localvoice` |
| 6 | Privacy/telemetry | Confirmed: 100% local, no data collection |
| 7 | macOS minimum version | Latest only |

---

## Parts (What We Build/Change)

Single shape — release prep has one path.

| Part | Mechanism | Flagged |
|------|-----------|---------|
| P1: Version alignment | Bump all versions to 1.0.0: `pyproject.toml`, `tauri.conf.json`, `Cargo.toml`, `manifest.json`, `app.py` | |
| P2: Company branding | Update identifier to `dev.majesticlabs.localvoice`. Update author → "Majestic Labs LLC". Add copyright "© 2026 Majestic Labs LLC". Add `homepage_url` / `repository` pointing to majesticlabs.dev. Update desktop window title. | |
| P3: MIT License | Create `LICENSE` at project root with MIT text, copyright Majestic Labs LLC | |
| P4: Privacy policy | Create `PRIVACY.md` — "we collect nothing" policy. Host URL at majesticlabs.dev/privacy (required for CWS) | |
| P5: Terms of service | Create `TERMS.md` — standard open-source "as-is" terms | |
| P6: Mac distribution (unsigned) | Build .dmg via Tauri, publish to GitHub Releases. README includes right-click → Open instructions for Gatekeeper bypass. majesticlabs.dev links to GitHub Releases. | ⚠️ Unsigned — users need Gatekeeper workaround until Apple Developer enrollment |
| P7: Chrome Web Store listing | Write store description, prepare screenshots (1280x800), promo images (440x280 small tile, 1400x560 marquee). Privacy policy URL. Submit for review. | |
| P8: Extension metadata | Update `manifest.json`: polish description, add `homepage_url: "https://majesticlabs.dev"` | |
| P9: README polish | Rewrite for end-users: what it does, install instructions (Mac app + extension), company info, links to majesticlabs.dev, CWS listing | |
| P10: GitHub Release workflow | GitHub Actions workflow to build .dmg on tag push, create release with artifact | |

---

## Fit Check: R × Parts

| Req | Requirement | P1 | P2 | P3 | P4 | P5 | P6 | P7 | P8 | P9 | P10 |
|-----|-------------|----|----|----|----|----|----|----|----|----|----|
| R0 | Ship downloadable Mac app + installable Chrome extension | | | | | | ✅ | ✅ | | | ✅ |
| R1 | All surfaces reference majesticlabs.dev + Majestic Labs LLC | | ✅ | ✅ | ✅ | ✅ | | ✅ | ✅ | ✅ | |
| R2 | Code-signed + notarized Mac app | | | | | | ❌ | | | | |
| R3 | Chrome extension on Chrome Web Store | | | | ✅ | | | ✅ | ✅ | | |
| R4 | Legal docs: MIT license, privacy, terms | | | ✅ | ✅ | ✅ | | | | | |
| R5 | Versions aligned at 1.0.0 | ✅ | | | | | | | | | |
| R6 | Distributed via GitHub Releases + majesticlabs.dev | | | | | | ✅ | ✅ | | ✅ | ✅ |
| R7 | Complete app metadata | ✅ | ✅ | | | | | ✅ | ✅ | | |
| R8 | Release-quality docs | | | | | | | | | ✅ | |

**Notes:**
- R2 fails: No Apple Developer account. Users must right-click → Open to bypass Gatekeeper. This is acceptable for v1.0 launch; enroll later for signed releases.

---

## Sequencing

**Phase 1 — Foundation (can do now, no external dependencies)**
1. P1: Version alignment
2. P2: Company branding
3. P3: MIT License
4. P4: Privacy policy
5. P5: Terms of service
6. P8: Extension metadata

**Phase 2 — Distribution infrastructure**
7. P10: GitHub Release workflow
8. P9: README polish

**Phase 3 — Store submission (depends on Phase 1 + assets)**
9. P7: Chrome Web Store listing assets + submission
10. P6: Mac distribution (build .dmg, publish first GitHub Release)

**Future — When Apple Developer account is obtained**
- Configure code signing + notarization in Tauri build
- Re-release signed .dmg
