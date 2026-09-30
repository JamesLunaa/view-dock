import Foundation
import SwiftUI

/// Captures touch/Pencil events from the video view and forwards them as
/// `input_event` messages (protocol/PROTOCOL.md) over the control data
/// channel. Coordinates are normalized to [0, 1] relative to the view's
/// bounds so the host can map them to real pixels on the virtual display.
struct TouchInputForwarder {
    var onEvent: (InputEventMessage) -> Void

    func handle(kind: InputKind, location: CGPoint, in bounds: CGRect, pressure: Double = 0) {
        let event = InputEventMessage(
            kind: kind,
            x: location.x / bounds.width,
            y: location.y / bounds.height,
            pressure: pressure,
            timestampMs: Int64(Date().timeIntervalSince1970 * 1000)
        )
        onEvent(event)
    }
}
