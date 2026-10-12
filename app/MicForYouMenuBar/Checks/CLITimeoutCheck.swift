import Foundation

// Regression check for the read-query timeout lifecycle. The timeout must
// bound the actual subprocess lifetime — including children that ignore
// SIGTERM — and cancellation must propagate to the child. Run from the
// repository root:
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
        try await expectTimeout(client, arguments: ["7"], timeout: 2, cap: 3.5)

        // Repeated slow queries leave nothing behind.
        for index in 1...3 {
            try await expectTimeout(client, arguments: ["5"], timeout: 1, cap: 2.5)
            print("PASS repeated slow query \(index)/3 bounded and stopped")
        }

        // A child that ignores SIGTERM must still be stopped and reaped:
        // graceful quit (1 s grace) → SIGKILL → confirmed exit.
        let stubborn = try stubbornFixture()
        do {
            let stub = CLIClient(executable: stubborn.python,
                                 projectRoot: URL(fileURLWithPath: "/tmp"),
                                 argumentsPrefix: [])
            _ = try await stub.run([stubborn.script.path, stubborn.pidfile.path],
                                   timeout: 0.5)
            preconditionFailure("stubborn child should have timed out")
        } catch let error as CLIError {
            guard case .readTimeout = error else {
                preconditionFailure("wrong error: \(error.localizedDescription)")
            }
        }
        let elapsed = stubborn.started.map { Date().timeIntervalSince($0) } ?? 0
        precondition(elapsed < 4.0, "stubborn child cost \(elapsed)s; grace+kill not enforced")
        print(String(format: "PASS stubborn child (ignores SIGTERM) stopped in %.2fs", elapsed))

        // PID-level proof of reaping, only for the child this check created.
        guard let pid = Int32(try String(contentsOf: stubborn.pidfile, encoding: .utf8)
            .trimmingCharacters(in: .whitespacesAndNewlines)) else {
            preconditionFailure("stubborn child did not write its PID")
        }
        try await assertGone(pid: pid)
        print("PASS stubborn child PID \(pid) reaped")

        // Cancellation propagates: cancelling the awaiting task stops the
        // child well before its own 8 s lifetime.
        let cancelStart = Date()
        let cancelTask = Task {
            try await client.run(["8"])
        }
        try await Task.sleep(for: .seconds(0.5))
        cancelTask.cancel()
        do {
            _ = try await cancelTask.value
            preconditionFailure("cancelled run should throw")
        } catch {
            // CancellationError or the timeout it triggers — either way the
            // child must be gone; assert bounded return.
        }
        let cancelled = Date().timeIntervalSince(cancelStart)
        precondition(cancelled < 4.0, "cancellation did not stop the child: \(cancelled)s")
        print(String(format: "PASS cancellation propagated in %.2fs (< 4s, child lifetime 8s)", cancelled))

        print("MicForYou CLI timeout check PASS")
    }

    private static func expectTimeout(_ client: CLIClient, arguments: [String],
                                      timeout: TimeInterval, cap: TimeInterval) async throws {
        let start = Date()
        do {
            _ = try await client.run(arguments, timeout: timeout)
            preconditionFailure("expected a readTimeout error")
        } catch let error as CLIError {
            guard case .readTimeout = error else {
                preconditionFailure("wrong error: \(error.localizedDescription)")
            }
        }
        let elapsed = Date().timeIntervalSince(start)
        precondition(elapsed < cap, "timeout not enforced: returned after \(elapsed)s")
        print(String(format: "PASS bounded timeout returns in %.2fs (< %.1fs)", elapsed, cap))
    }

    private static func assertGone(pid: Int32) async throws {
        let kill = CLIClient(executable: URL(filePath: "/usr/bin/kill"),
                             projectRoot: URL(fileURLWithPath: "/tmp"),
                             argumentsPrefix: [])
        do {
            _ = try await kill.run(["-0", String(pid)])
            preconditionFailure("PID \(pid) still alive after reported stop")
        } catch {
            // Non-zero exit = no such process, exactly what we want.
        }
    }

    private struct StubbornFixture {
        let python: URL
        let script: URL
        let pidfile: URL
        let started: Date?
    }

    /// A child that writes its PID to a file and then ignores SIGTERM.
    private static func stubbornFixture() throws -> StubbornFixture {
        let work = FileManager.default.temporaryDirectory
            .appending(path: "mfy-stubborn-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: work, withIntermediateDirectories: true)
        let script = work.appending(path: "ignore_term.py")
        let pidfile = work.appending(path: "child.pid")
        try """
        import os, signal, sys, time
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        with open(sys.argv[1], "w") as handle:
            handle.write(str(os.getpid()))
        time.sleep(60)
        """.write(to: script, atomically: true, encoding: .utf8)
        let python = URL(filePath: "/usr/bin/python3")
        guard FileManager.default.isExecutableFile(atPath: python.path) else {
            throw NSError(domain: "CLITimeoutCheck", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: "python3 missing"])
        }
        return StubbornFixture(python: python, script: script, pidfile: pidfile,
                               started: Date())
    }
}
