import AVFoundation
import SwiftUI

/// Hosts the wired stream's `AVSampleBufferDisplayLayer` in SwiftUI. The layer
/// is owned by `WiredClient`; this view only gives it a place on screen and
/// keeps it sized to the view.
struct WiredVideoView: UIViewRepresentable {
    let displayLayer: AVSampleBufferDisplayLayer

    func makeUIView(context: Context) -> LayerHostView {
        LayerHostView(hosting: displayLayer)
    }

    func updateUIView(_ uiView: LayerHostView, context: Context) {}

    final class LayerHostView: UIView {
        private let hosted: AVSampleBufferDisplayLayer

        init(hosting displayLayer: AVSampleBufferDisplayLayer) {
            hosted = displayLayer
            super.init(frame: .zero)
            backgroundColor = .black
            layer.addSublayer(displayLayer)
        }

        @available(*, unavailable)
        required init?(coder: NSCoder) {
            fatalError("init(coder:) is not supported")
        }

        override func layoutSubviews() {
            super.layoutSubviews()
            // Resize without the implicit animation CALayer would otherwise add.
            CATransaction.begin()
            CATransaction.setDisableActions(true)
            hosted.frame = bounds
            CATransaction.commit()
        }
    }
}
