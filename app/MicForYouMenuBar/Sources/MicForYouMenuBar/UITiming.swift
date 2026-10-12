import Foundation

/// Lightweight UI stage timing for the settings-window responsiveness
/// acceptance: append-only JSONL under the app's logs directory, one line per
/// stage event (open requested, window appeared, data loaded). Never blocks
/// the main thread; failures to write are silently dropped — timing evidence
/// must never become a new failure mode for users.
enum UITiming {
    private static let queue = DispatchQueue(label: "micforyou.uitiming")

    static func event(_ name: String, _ detail: [String: String] = [:]) {
        let stamp = Date().timeIntervalSince1970
        queue.async {
            let directory = FileManager.default.homeDirectoryForCurrentUser
                .appending(path: "Library/Application Support/MicForYou/logs")
            try? FileManager.default.createDirectory(at: directory,
                                                     withIntermediateDirectories: true)
            let payload: [String: Any] = ["event": name, "ts": stamp, "detail": detail]
            guard var line = try? JSONSerialization.data(withJSONObject: payload) else {
                return
            }
            line.append(Data("\n".utf8))
            let url = directory.appending(path: "ui-timing.jsonl")
            if let handle = try? FileHandle(forWritingTo: url) {
                try? handle.seekToEnd()
                try? handle.write(line)
                try? handle.close()
            } else {
                try? line.write(to: url, options: .atomic)
            }
        }
    }
}
