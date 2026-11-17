// tekbro-hotkey: registers global hotkeys and prints the action name on stdout
// each time one is pressed. Uses Carbon RegisterEventHotKey, which needs no
// Accessibility / Input Monitoring permission.
//
//   tekbro-hotkey solve=ctrl+alt+s answer=ctrl+alt+a

import AppKit
import Carbon

let keyCodes: [String: UInt32] = [
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9,
    "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "1": 18, "2": 19,
    "3": 20, "4": 21, "6": 22, "5": 23, "9": 25, "7": 26, "8": 28, "0": 29, "o": 31,
    "u": 32, "i": 34, "p": 35, "l": 37, "j": 38, "k": 40, "n": 45, "m": 46,
    "space": 49, "return": 36, "enter": 36, "/": 44, ".": 47, ";": 41,
]

func log(_ s: String) {
    FileHandle.standardError.write(("[tekbro-hotkey] " + s + "\n").data(using: .utf8)!)
}

func parse(_ combo: String) -> (key: UInt32, mods: UInt32)? {
    var mods: UInt32 = 0
    var key: UInt32?
    for part in combo.lowercased().split(separator: "+").map(String.init) {
        switch part {
        case "cmd", "command": mods |= UInt32(cmdKey)
        case "alt", "opt", "option": mods |= UInt32(optionKey)
        case "ctrl", "control": mods |= UInt32(controlKey)
        case "shift": mods |= UInt32(shiftKey)
        default: key = keyCodes[part]
        }
    }
    guard let k = key, mods != 0 else { return nil }
    return (k, mods)
}

func emit(_ line: String) {
    let data = Array((line + "\n").utf8)
    data.withUnsafeBytes { buf in
        if Darwin.write(STDOUT_FILENO, buf.baseAddress, buf.count) <= 0 { exit(0) }  // parent gone
    }
}

var actions: [String] = []

@main
struct TekBroHotkey {
    static func main() {
        signal(SIGPIPE, SIG_IGN)
        var eventType = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        InstallEventHandler(GetApplicationEventTarget(), { _, event, _ in
            var hk = EventHotKeyID()
            GetEventParameter(event, EventParamName(kEventParamDirectObject), EventParamType(typeEventHotKeyID),
                              nil, MemoryLayout<EventHotKeyID>.size, nil, &hk)
            let i = Int(hk.id)
            if i < actions.count { emit(actions[i]) }
            return noErr
        }, 1, &eventType, nil, nil)

        for arg in CommandLine.arguments.dropFirst() {
            let kv = arg.split(separator: "=", maxSplits: 1).map(String.init)
            guard kv.count == 2, let (key, mods) = parse(kv[1]) else { log("bad hotkey: \(arg)"); exit(2) }
            var ref: EventHotKeyRef?
            let id = EventHotKeyID(signature: OSType(0x544B4252), id: UInt32(actions.count))  // 'TKBR'
            let status = RegisterEventHotKey(key, mods, id, GetApplicationEventTarget(), 0, &ref)
            if status != noErr { log("could not register \(kv[1]) (in use by another app?) status=\(status)"); continue }
            actions.append(kv[0])
            log("\(kv[1]) → \(kv[0])")
        }
        if actions.isEmpty { exit(2) }

        let parent = getppid()
        Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { _ in
            if getppid() != parent { exit(0) }
        }
        let app = NSApplication.shared
        app.setActivationPolicy(.prohibited)  // no Dock icon, no menu bar
        app.run()
    }
}
