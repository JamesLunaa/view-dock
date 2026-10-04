// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 James Luna

import Foundation

/// The facts the About screen states, kept Foundation-only so they can be unit-tested.
/// The bundled texts under `Resources/Legal/` are generated from the repo's LICENSE and
/// `legal/components.json` by `scripts/generate_legal.py` — don't edit them by hand.
enum AppInfo {
    static let name = "view-dock"
    static let copyright = "Copyright (C) 2026 James Luna"
    static let sourceURL = URL(string: "https://github.com/JamesLunaa/view-dock")!

    /// The two notices the GPL requires an interactive program to show (GPL-3.0 §5(d)).
    static let freeSoftwareNotice =
        "view-dock is free software: you can redistribute it and/or modify it under the terms of "
        + "the GNU General Public License as published by the Free Software Foundation, either "
        + "version 3 of the License, or (at your option) any later version."
    static let noWarrantyNotice = "This program comes with ABSOLUTELY NO WARRANTY."

    /// Where the bundled license texts live inside the app bundle (a folder reference).
    static let legalSubdirectory = "Legal"
    static let licenseResource = "gpl-3.0"
    static let noticesResource = "notices"

    /// "Version 2.0.0 (1)" from the app's Info.plist values; just the version when the build
    /// number is the same, and "Version unknown" if the plist has neither.
    static func versionDescription(from info: [String: Any]?) -> String {
        let short = info?["CFBundleShortVersionString"] as? String
        let build = info?["CFBundleVersion"] as? String
        switch (short, build) {
        case let (short?, build?) where build != short:
            return "Version \(short) (\(build))"
        case let (short?, _):
            return "Version \(short)"
        default:
            return "Version unknown"
        }
    }
}
