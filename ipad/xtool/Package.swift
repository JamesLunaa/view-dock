// swift-tools-version:6.0
// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 James Luna

//
// Builds the iPad app with xtool (https://xtool.sh) on Linux, without a Mac:
// `xtool dev` from this directory builds, signs and installs it over USB.
// `project.yml` + XcodeGen remains the Xcode build; both compile the same
// `ipad/Sources` (Sources/ViewDock is a symlink to it).
import PackageDescription

let package = Package(
    name: "ViewDock",
    platforms: [.iOS(.v17)],
    products: [
        // xtool packs the package's single library product as the app.
        .library(name: "ViewDock", targets: ["ViewDock"]),
    ],
    dependencies: [
        .package(url: "https://github.com/stasel/WebRTC.git", from: "137.0.0"),
    ],
    targets: [
        .target(
            name: "ViewDock",
            dependencies: [.product(name: "WebRTC", package: "WebRTC")],
            path: "Sources/ViewDock",
            swiftSettings: [.swiftLanguageMode(.v5)]
        ),
    ]
)
