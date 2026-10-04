// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 James Luna

import SwiftUI
import WebRTC

/// Wraps the WebRTC Metal renderer for use in SwiftUI, re-attaching itself
/// whenever the underlying track changes (e.g. once negotiation completes).
struct RemoteVideoView: UIViewRepresentable {
    let track: RTCVideoTrack?

    func makeUIView(context: Context) -> RTCMTLVideoView {
        let view = RTCMTLVideoView()
        view.videoContentMode = .scaleAspectFit
        return view
    }

    func updateUIView(_ uiView: RTCMTLVideoView, context: Context) {
        context.coordinator.attach(track: track, to: uiView)
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    final class Coordinator {
        private weak var attachedTrack: RTCVideoTrack?

        func attach(track: RTCVideoTrack?, to view: RTCMTLVideoView) {
            guard track !== attachedTrack else { return }
            attachedTrack?.remove(view)
            attachedTrack = track
            track?.add(view)
        }
    }
}
