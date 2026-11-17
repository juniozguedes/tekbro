// tekbro-audio: captures macOS system audio with ScreenCaptureKit and writes
// raw 16 kHz mono float32 PCM to stdout.
//
//   tekbro-audio                 # all system audio (except this process)
//   tekbro-audio --app Teams     # only apps whose name contains "Teams"
//   tekbro-audio --list          # list running apps that can be captured
//
// Requires the Screen Recording permission for the terminal that launches it.

import AVFoundation
import CoreMedia
import Foundation
import ScreenCaptureKit

func log(_ s: String) {
    FileHandle.standardError.write(("[tekbro-audio] " + s + "\n").data(using: .utf8)!)
}

final class Capturer: NSObject, SCStreamOutput, SCStreamDelegate {
    private var stream: SCStream?
    private var counts = [0, 0]
    private var written = 0
    private let debug = ProcessInfo.processInfo.environment["TEKBRO_AUDIO_DEBUG"] != nil
    private let audioQueue = DispatchQueue(label: "tekbro.audio")
    private let videoQueue = DispatchQueue(label: "tekbro.video")

    func start(appFilter: String?) async throws {
        let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: false)
        guard let display = content.displays.first else { throw NSError(domain: "tekbro", code: 1, userInfo: [NSLocalizedDescriptionKey: "no display"]) }

        let filter: SCContentFilter
        if let name = appFilter?.lowercased() {
            let apps = content.applications.filter {
                $0.applicationName.lowercased().contains(name) || $0.bundleIdentifier.lowercased().contains(name)
            }
            if apps.isEmpty { throw NSError(domain: "tekbro", code: 2, userInfo: [NSLocalizedDescriptionKey: "no running app matches '\(name)' (use --list)"]) }
            log("capturing: " + apps.map { $0.applicationName }.joined(separator: ", "))
            filter = SCContentFilter(display: display, including: apps, exceptingWindows: [])
        } else {
            log("capturing: all system audio")
            filter = SCContentFilter(display: display, excludingApplications: [], exceptingWindows: [])
        }

        let cfg = SCStreamConfiguration()
        cfg.capturesAudio = true
        cfg.excludesCurrentProcessAudio = true
        cfg.sampleRate = 16_000
        cfg.channelCount = 1
        // We only want audio; keep the video side as cheap as possible.
        cfg.width = 2
        cfg.height = 2

        let s = SCStream(filter: filter, configuration: cfg, delegate: self)
        try s.addStreamOutput(self, type: .audio, sampleHandlerQueue: audioQueue)
        try s.addStreamOutput(self, type: .screen, sampleHandlerQueue: videoQueue)  // avoids "dropping frame" spam
        try await s.startCapture()
        stream = s
        log("started")
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer sb: CMSampleBuffer, of type: SCStreamOutputType) {
        if debug { counts[type == .audio ? 0 : 1] += 1; if (counts[0] + counts[1]) % 20 == 1 { log("callbacks audio=\(counts[0]) screen=\(counts[1]) bytes=\(written)") } }
        guard type == .audio, sb.isValid else { return }
        do {
            try sb.withAudioBufferList { abl, _ in
                // channelCount = 1 → a single float32 buffer
                if let buf = abl.first, let data = buf.mData {
                    // POSIX write: FileHandle.write raises an ObjC exception on a broken pipe.
                    var ptr = UnsafeRawPointer(data), left = Int(buf.mDataByteSize)
                    while left > 0 {
                        let n = Darwin.write(STDOUT_FILENO, ptr, left)
                        if n <= 0 { if errno == EINTR { continue }; exit(0) }  // Tek Bro went away
                        ptr += n; left -= n
                    }
                    written += Int(buf.mDataByteSize)
                }
            }
        } catch {
            log("buffer error: \(error)")
        }
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        log("stopped: \(error.localizedDescription)")
        exit(1)
    }
}

@main
struct TekBroAudio {
    // Must outlive main(): if the capturer (and its SCStream) is released,
    // capture silently stops after the first frame.
    static var capturer: Capturer?

    static func main() {
        let args = CommandLine.arguments
        signal(SIGPIPE, SIG_IGN)

        if args.contains("--list") {
            Task {
                do {
                    let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: false)
                    for app in content.applications.sorted(by: { $0.applicationName < $1.applicationName }) where !app.applicationName.isEmpty {
                        print("\(app.applicationName)\t\(app.bundleIdentifier)")
                    }
                    exit(0)
                } catch {
                    log("error: \(error.localizedDescription)")
                    exit(1)
                }
            }
        } else {
            var appFilter: String? = nil
            if let i = args.firstIndex(of: "--app"), i + 1 < args.count { appFilter = args[i + 1] }
            let c = Capturer()
            capturer = c
            Task {
                do {
                    try await c.start(appFilter: appFilter)
                } catch {
                    log("error: \(error.localizedDescription)")
                    exit(1)
                }
            }
        }

        // Exit when the parent (Tek Bro) goes away.
        let parent = getppid()
        Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { _ in
            if getppid() != parent { exit(0) }
        }
        RunLoop.main.run()
    }
}
