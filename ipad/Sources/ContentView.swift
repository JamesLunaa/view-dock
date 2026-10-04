// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 James Luna

import SwiftUI

struct ContentView: View {
    @StateObject private var connectionManager = ConnectionManager()
    @State private var hostAddress = ""

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()

            if let wired = connectionManager.wiredClient {
                WiredConnectedView(client: wired)
            } else if let client = connectionManager.webRTCClient {
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

/// The wired stream: the video layer is sized to the host display's aspect ratio
/// so there are no letterbox bars, which means a touch location within this
/// view maps 1:1 onto the host display.
private struct WiredConnectedView: View {
    @ObservedObject var client: WiredClient
    @State private var forwarder: TouchInputForwarder?
    @State private var isTouching = false

    var body: some View {
        let aspect = client.displayInfo.map { CGFloat($0.width) / CGFloat($0.height) } ?? (16.0 / 9.0)
        WiredVideoView(displayLayer: client.displayLayer)
            .aspectRatio(aspect, contentMode: .fit)
            .overlay(
                GeometryReader { geometry in
                    Color.clear
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
            )
            .frame(maxWidth: .infinity, maxHeight: .infinity)
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
