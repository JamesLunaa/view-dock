import Foundation
import SwiftUI

/// Captures touch/Pencil events from the video view and forwards them as
/// `input_event` messages (protocol/PROTOCOL.md) over the control data
/// channel. Coordinates are normalized to [0, 1] relative to the view's
/// bounds so the host can map them to real pixels on the virtual display.
struct TouchInputForwarder {
    var onEvent: (InputEventMessage) -> Void

    func handle(kind: InputKind, location: CGPoint, in bounds: CGRect, pressure: Double = 0) {
        guard bounds.width > 0, bounds.height > 0 else { return }
        let event = InputEventMessage(
            kind: kind,
            x: Self.clampUnit(location.x / bounds.width),
            y: Self.clampUnit(location.y / bounds.height),
            pressure: Self.clampUnit(pressure),
            timestampMs: Int64(Date().timeIntervalSince1970 * 1000)
        )
        onEvent(event)
    }

    private static func clampUnit(_ value: Double) -> Double {
        min(1, max(0, value))
    }
}
