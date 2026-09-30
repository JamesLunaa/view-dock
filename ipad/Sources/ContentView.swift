import SwiftUI

struct ContentView: View {
    @StateObject private var connectionManager = ConnectionManager()
    @State private var hostAddress = ""

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()

            if let client = connectionManager.webRTCClient {
                ConnectedView(client: client)
            } else {
                VStack(spacing: 16) {
                    Text(connectionManager.statusDescription)
                        .foregroundStyle(.white)

                    TextField("Host IP address", text: $hostAddress)
                        .textFieldStyle(.roundedBorder)
                        .keyboardType(.decimalPad)
                        .autocorrectionDisabled()
                        .frame(maxWidth: 240)

                    Button("Connect over Wi-Fi") {
                        connectionManager.connectOverWifi(hostAddress: hostAddress)
                    }
                    .disabled(hostAddress.isEmpty)
                }
            }
        }
        .onAppear {
            connectionManager.start()
        }
    }
}

/// Full-screen video render + touch/Pencil capture once negotiation with the
/// host has completed. Pencil-specific handling (pressure, hover) is a
/// follow-up — this ships plain touch forwarding first.
private struct ConnectedView: View {
    @ObservedObject var client: WebRTCClient
    @State private var forwarder: TouchInputForwarder?
    @State private var isTouching = false

    var body: some View {
        GeometryReader { geometry in
            RemoteVideoView(track: client.remoteVideoTrack)
                .contentShape(Rectangle())
                .gesture(
                    DragGesture(minimumDistance: 0)
                        .onChanged { value in
                            let kind: InputKind = isTouching ? .touchMove : .touchDown
                            isTouching = true
                            forward(kind, at: value.location, in: geometry.size)
                        }
                        .onEnded { value in
                            isTouching = false
                            forward(.touchUp, at: value.location, in: geometry.size)
                        }
                )
        }
        .ignoresSafeArea()
        .onAppear {
            forwarder = TouchInputForwarder { event in
                client.sendInputEvent(event)
            }
        }
    }

    private func forward(_ kind: InputKind, at location: CGPoint, in size: CGSize) {
        forwarder?.handle(kind: kind, location: location, in: CGRect(origin: .zero, size: size))
    }
}

#Preview {
    ContentView()
}
