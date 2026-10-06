import SwiftUI

@main
struct MicForYouMenuBarApp: App {
    @StateObject private var model = AppModel()

    var body: some Scene {
        MenuBarExtra {
            MenuContentView(model: model)
        } label: {
            Image(systemName: model.status?.runtime.effectiveStatus == "RUNNING"
                ? "waveform.badge.mic"
                : "mic")
        }
        .menuBarExtraStyle(.window)

        Settings {
            SettingsView(model: model)
        }
    }
}
