import Foundation

// Regression check for the read-query timeout: the timeout must bound the
// actual subprocess lifetime (terminate + reap), not just race a timer while
// an unresponsive child keeps the UI task pending. Run from the repository
// root:
//   swiftc -parse-as-library \
//     app/MicForYouMenuBar/Sources/MicForYouMenuBar/CLIClient.swift \
//     app/MicForYouMenuBar/Checks/CLITimeoutCheck.swift \
//     -o .build/cli-timeout-check && ./.build/cli-timeout-check

@main
struct CLITimeoutCheck {
    static func main() async throws {
        let client = CLIClient(executable: URL(filePath: "/bin/sleep"),
                               projectRoot: URL(fileURLWithPath: "/tmp"),
                               argumentsPrefix: [])

        // Control: an unbounded call still waits for quick children.
        let data = try await client.run(["0.2"])
        print("PASS quick command returns (bytes: \(data.count))")

        // Bounded wait: a 7 s child under a 2 s timeout must fail at ~2 s —
        // previously this returned only after the child exited (7.0 s).
        let start = Date()
        do {
            _ = try await client.run(["7"], timeout: 2)
            preconditionFailure("expected a readTimeout error")
        } catch let error as CLIError {
            guard case .readTimeout = error else {
                preconditionFailure("wrong error: \(error.localizedDescription)")
            }
        } catch {
            preconditionFailure("unexpected error type: \(error)")
        }
        let elapsed = Date().timeIntervalSince(start)
        precondition(elapsed < 3.0, "timeout not enforced: returned after \(elapsed)s")
        print(String(format: "PASS bounded timeout returns in %.2fs (< 3s, not 7s)", elapsed))

        // The terminated child must actually be gone, not left behind.
        let probe = CLIClient(executable: URL(filePath: "/usr/bin/pgrep"),
                              projectRoot: URL(fileURLWithPath: "/tmp"),
                              argumentsPrefix: [])
        let leftovers = (try? await probe.run(["-x", "sleep"])) ?? Data()
        precondition(leftovers.isEmpty, "sleep child survived termination")
        print("PASS terminated child reaped")

        print("MicForYou CLI timeout check PASS")
    }
}
