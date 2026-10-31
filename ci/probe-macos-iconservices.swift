import AppKit
import Foundation

// Match Unity's batchmode default importer: obtaining the icon is not
// sufficient; request its image bytes to exercise IconServices rendering.
let image = NSWorkspace.shared.icon(forFileType: "txt")
_ = image.tiffRepresentation
print("icon-request-returned")
