// swift-tools-version:5.9
// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 James Luna

//
// Not how the app is built (that's `project.yml` + XcodeGen). This package exists
// only so the Foundation-only logic — protocol messages, WebSocket framing,
// H.264 Annex-B parsing — can be unit-tested with `swift test` on macOS *or*
// Linux, without Xcode, a simulator or a device. Everything that touches
// UIKit/AVFoundation/Network stays out of it.
import PackageDescription

let package = Package(
    name: "ViewDockLogic",
    targets: [
        .target(
            name: "ViewDockLogic",
            path: "Sources",
            // Everything else in Sources/ needs UIKit/AVFoundation/Network/WebRTC,
            // which only exist on Apple platforms — it is built by Xcode, not here.
            exclude: [
                "ViewDockApp.swift",
                "ContentView.swift",
                "Input",
                "Legal/AboutView.swift",
                "Networking/ConnectionManager.swift",
                "Networking/H264SampleBufferFactory.swift",
                "Networking/HostDiscovery.swift",
                "Networking/RTCPeerConnection+Async.swift",
                "Networking/RemoteVideoView.swift",
                "Networking/SignalingChannel.swift",
                "Networking/Transport.swift",
                "Networking/WebRTCClient.swift",
                "Networking/WebSocketServer.swift",
                "Networking/WiredClient.swift",
                "Networking/WiredVideoView.swift",
            ],
            sources: [
                "Protocol/Messages.swift",
                "Networking/WebSocketFraming.swift",
                "Networking/H264AnnexB.swift",
                "Networking/DiscoveredHost.swift",
                "Legal/AppInfo.swift",
            ]
        ),
        .testTarget(
            name: "ViewDockLogicTests",
            dependencies: ["ViewDockLogic"],
            path: "Tests/ViewDockLogicTests"
        ),
    ]
)
