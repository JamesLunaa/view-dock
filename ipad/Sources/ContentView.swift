import SwiftUI

struct ContentView: View {
    @StateObject private var connectionManager = ConnectionManager()

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()

            // TODO: replace with the WebRTC video render view once
            // WebRTCClient exposes a renderable frame/layer.
            Text(connectionManager.statusDescription)
                .foregroundStyle(.white)
        }
        .onAppear {
            connectionManager.start()
        }
    }
}

#Preview {
    ContentView()
}
