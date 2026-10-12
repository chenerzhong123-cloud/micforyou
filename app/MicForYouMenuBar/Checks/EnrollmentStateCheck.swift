import Foundation

// Regression check for the registration window's state machine: verifies
// state transitions and task identity, not button strings. Run from the
// repository root:
//   swiftc -parse-as-library app/MicForYouMenuBar/Sources/MicForYouMenuBar/Models.swift \
//     app/MicForYouMenuBar/Checks/EnrollmentStateCheck.swift -o .build/enrollment-state-check

@main
struct EnrollmentStateCheck {
    static func job(_ status: String, phase: String? = nil, token: String? = nil) -> SetupJob {
        SetupJob(status: status, stage: "stage", progress: 0.5, phase: phase,
                 reason: nil, token: token, voice: nil, performance: nil,
                 performanceReason: nil, recording: nil)
    }

    static func expect(_ actual: EnrollmentFlow.State, _ expected: EnrollmentFlow.State,
                       _ name: String) {
        precondition(actual == expected, "\(name): expected \(expected), got \(actual)")
        print("PASS \(name)")
    }

    static func main() {
        // No persisted job at all (fresh install): preview state.
        expect(EnrollmentFlow.state(job: nil, attemptToken: nil), .idle, "no job -> preview")

        // Stale READY from an earlier attempt (app restart or reopened sheet):
        // must NOT present as this window's completion.
        expect(EnrollmentFlow.state(job: job("READY", token: "old"), attemptToken: nil),
               .idle, "stale READY -> preview")
        expect(EnrollmentFlow.state(job: job("READY", token: "old"), attemptToken: "new"),
               .idle, "foreign-token READY -> preview")

        // This attempt's READY is the only one that completes.
        expect(EnrollmentFlow.state(job: job("READY", token: "mine"), attemptToken: "mine"),
               .done, "own-token READY -> done")

        // Adopted RUNNING job (window reopened while worker is active).
        expect(EnrollmentFlow.state(job: job("RUNNING", phase: "countdown", token: "w"),
                                    attemptToken: "w"), .countdown, "adopted countdown")
        expect(EnrollmentFlow.state(job: job("RUNNING", phase: "recording", token: "w"),
                                    attemptToken: "w"), .recording, "adopted recording")
        expect(EnrollmentFlow.state(job: job("RUNNING", phase: "checking", token: "w"),
                                    attemptToken: "w"), .checking, "adopted checking")
        expect(EnrollmentFlow.state(job: job("RUNNING", phase: "preparing_model", token: "w"),
                                    attemptToken: "w"), .preparing, "adopted preparing")
        expect(EnrollmentFlow.state(job: job("RUNNING", phase: nil, token: "w"),
                                    attemptToken: "w"), .preparing, "legacy running phase")

        // FAILED (own or stale) offers the retry path.
        expect(EnrollmentFlow.state(job: job("FAILED", token: "mine"), attemptToken: "mine"),
               .failed, "own failure -> retry")
        expect(EnrollmentFlow.state(job: job("FAILED", token: "old"), attemptToken: nil),
               .failed, "stale failure -> retry")

        // Cancelled or idle jobs restart from the preview.
        expect(EnrollmentFlow.state(job: job("CANCELLED", token: "mine"), attemptToken: "mine"),
               .idle, "cancelled -> preview")

        // Voice saved + performance verdicts.
        func saved(_ status: String, performance: String?, reason: String? = nil) -> SetupJob {
            SetupJob(status: status, stage: "s", progress: 0.5, phase: nil,
                     reason: nil, token: "w", voice: "saved",
                     performance: performance, performanceReason: reason, recording: nil)
        }
        expect(EnrollmentFlow.state(job: saved("WAITING", performance: "latency_warning"),
                                    attemptToken: "w"), .waitingTrial,
               "saved + latency warning -> trial choice")
        expect(EnrollmentFlow.state(job: saved("WAITING", performance: "blocked"),
                                    attemptToken: "w"), .performanceBlocked,
               "saved + blocked -> retest")
        expect(EnrollmentFlow.state(job: saved("FAILED", performance: "blocked",
                                               reason: "underrun"),
                                    attemptToken: "w"), .performanceBlocked,
               "failed with saved voice -> retest not re-record")
        expect(EnrollmentFlow.state(job: job("FAILED", token: "w"),
                                    attemptToken: nil), .failed,
               "failed without saved voice -> recording retry")
        expect(EnrollmentFlow.state(job: saved("CANCELLED", performance: nil),
                                    attemptToken: "w"), .idle,
               "cancelled saved voice -> preview")


        print("MicForYou enrollment state check PASS")
    }
}
