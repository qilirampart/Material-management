import Cocoa
import Foundation

let releaseVersion = "__VERSION__"
let assetName = "DianzhongMaterialAssistant-macos-\(releaseVersion).zip"
let assetURL = URL(string: "https://github.com/qilirampart/Material-management/releases/download/v\(releaseVersion)/\(assetName)")!

final class AppDelegate: NSObject, NSApplicationDelegate, URLSessionDownloadDelegate {
    private var window: NSWindow!
    private var status: NSTextField!
    private var progress: NSProgressIndicator!

    func applicationDidFinishLaunching(_ notification: Notification) {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 500, height: 190), styleMask: [.titled, .closable], backing: .buffered, defer: false)
        window.title = "Dianzhong Material Assistant - Online Installer"
        let content = NSView(frame: window.contentView!.bounds)
        content.autoresizingMask = [.width, .height]
        let title = NSTextField(labelWithString: "Dianzhong Material Assistant")
        title.font = NSFont.systemFont(ofSize: 22, weight: .bold)
        title.frame = NSRect(x: 28, y: 124, width: 420, height: 30)
        content.addSubview(title)
        status = NSTextField(labelWithString: "Downloading the latest full package…")
        status.frame = NSRect(x: 28, y: 88, width: 440, height: 24)
        content.addSubview(status)
        progress = NSProgressIndicator(frame: NSRect(x: 28, y: 54, width: 444, height: 16))
        progress.minValue = 0; progress.maxValue = 100; progress.isIndeterminate = false
        content.addSubview(progress)
        window.contentView = content
        window.center(); window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true)
        URLSession(configuration: .default, delegate: self, delegateQueue: .main).downloadTask(with: assetURL).resume()
    }

    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask, didWriteData bytesWritten: Int64, totalBytesWritten: Int64, totalBytesExpectedToWrite: Int64) {
        guard totalBytesExpectedToWrite > 0 else { return }
        let percent = Double(totalBytesWritten) * 100 / Double(totalBytesExpectedToWrite)
        progress.doubleValue = percent
        status.stringValue = String(format: "Downloading: %.1f / %.1f MB", Double(totalBytesWritten) / 1_048_576, Double(totalBytesExpectedToWrite) / 1_048_576)
    }

    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask, didFinishDownloadingTo location: URL) {
        do {
            let downloads = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask)[0]
            let target = downloads.appendingPathComponent(assetName)
            try? FileManager.default.removeItem(at: target)
            try FileManager.default.moveItem(at: location, to: target)
            progress.doubleValue = 100
            status.stringValue = "Download complete. Opened in Finder."
            NSWorkspace.shared.activateFileViewerSelecting([target])
        } catch {
            status.stringValue = "Could not save the download: \(error.localizedDescription)"
        }
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        if let error = error { status.stringValue = "Download failed: \(error.localizedDescription)" }
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
