import AppKit
import Foundation

@main
struct BundleCheck {
    static func main() throws {
        guard CommandLine.arguments.count == 2 else {
            fatalError("Usage: bundle-check /path/to/MicForYou.app")
        }
        let root = URL(fileURLWithPath: CommandLine.arguments[1])
        let plistURL = root.appendingPathComponent("Contents/Info.plist")
        let plist = try PropertyListSerialization.propertyList(
            from: Data(contentsOf: plistURL), options: [], format: nil
        ) as! [String: Any]
        precondition(plist["CFBundleIdentifier"] as? String == "com.micforyou.menubar")
        precondition(plist["LSUIElement"] as? Bool == true)
        precondition(plist["CFBundleIconFile"] as? String == "AppIcon.icns")
        let iconURL = root.appendingPathComponent("Contents/Resources/AppIcon.icns")
        guard let icon = NSImage(contentsOf: iconURL), icon.isValid else {
            fatalError("Bundled icon cannot be decoded")
        }
        let widths = Set(icon.representations.map { $0.pixelsWide })
        precondition(Set([16, 32, 64, 128, 256, 512, 1024]).isSubset(of: widths))
        precondition(icon.representations.allSatisfy { $0.pixelsWide == $0.pixelsHigh })
        print("MicForYou bundle + C01 icon check PASS (16–1024 px)")
    }
}
