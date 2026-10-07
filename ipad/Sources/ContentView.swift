// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 James Luna

import SwiftUI

struct ContentView: View {
    @StateObject private var connectionManager = ConnectionManager()
    @StateObject private var discovery = HostDiscovery()
    @State private var searchedAWhile = false
    @State private var hostAddress = ""
    @State private var showingAbout = false

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

                    // A tap is always required: anyone on the network can advertise a host,
                    // and there is no authentication yet (see SECURITY.md), so never connect silently.
                    ForEach(discovery.hosts) { host in
                        Button(host.isCompatible ? "\(host.name) (\(host.address))"
                                                 : "\(host.name) — needs a different app version") {
                            connectionManager.connect(to: host)
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(!host.isCompatible)
                    }
                    if discovery.hosts.isEmpty {
                        Text(discoveryHint)
                            .foregroundStyle(.gray)
                            .multilineTextAlignment(.center)
                    }

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
                // Browsing only while the connect screen is showing: it keeps the Wi-Fi radio busy.
                .onAppear { discovery.start() }
                .onDisappear { discovery.stop() }
                .task {
                    searchedAWhile = false
                    try? await Task.sleep(for: .seconds(5))
                    searchedAWhile = true
                }
            }
        }
        .overlay(alignment: .topTrailing) {
            // Only while no session is running: during one the screen is the host's display.
            if connectionManager.wiredClient == nil, connectionManager.webRTCClient == nil {
                Button {
                    showingAbout = true
                } label: {
                    Image(systemName: "info.circle")
                        .font(.title2)
                        .foregroundStyle(.white)
                        .padding()
                }
                .accessibilityLabel("About")
            }
        }
        .sheet(isPresented: $showingAbout) {
            AboutView()
        }
        .onAppear {
            connectionManager.start()
        }
    }
}

extension ContentView {
    fileprivate var discoveryHint: String {
        if let reason = discovery.unavailableReason { return reason }
        return searchedAWhile
            ? "Not finding your computer? Enter its IP address below."
            : "Searching for hosts…"
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
