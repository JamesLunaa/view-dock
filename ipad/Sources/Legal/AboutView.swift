// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 James Luna

import SwiftUI

/// The legal notices screen. Besides being good manners, a GPL program with a user
/// interface has to show its copyright, say there is no warranty, and tell the user how
/// to see the license (GPL-3.0 §5(d)) — this is that.
struct AboutView: View {
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Text(AppInfo.name)
                        .font(.title2.bold())
                    Text(AppInfo.versionDescription(from: Bundle.main.infoDictionary))
                        .foregroundStyle(.secondary)
                    Text(AppInfo.copyright)
                }

                Section {
                    Text(AppInfo.freeSoftwareNotice)
                    Text(AppInfo.noWarrantyNotice)
                }

                Section {
                    NavigationLink("License (GNU GPL v3)") {
                        LegalTextView(title: "License (GNU GPL v3)", resource: AppInfo.licenseResource)
                    }
                    NavigationLink("Third-party licenses") {
                        LegalTextView(title: "Third-party licenses", resource: AppInfo.noticesResource)
                    }
                    Link("Source code", destination: AppInfo.sourceURL)
                }
            }
            .navigationTitle("About")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }
}

/// A long text file from the app bundle (the GPL, or the third-party notices) in a
/// scrolling, monospaced, selectable view.
struct LegalTextView: View {
    let title: String
    let resource: String

    @State private var text = "Loading…"

    var body: some View {
        ScrollView {
            Text(text)
                .font(.system(.caption2, design: .monospaced))
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding()
        }
        .navigationTitle(title)
        .navigationBarTitleDisplayMode(.inline)
        .task { text = Self.load(resource) }
    }

    private static func load(_ resource: String) -> String {
        guard
            let url = Bundle.main.url(
                forResource: resource,
                withExtension: "txt",
                subdirectory: AppInfo.legalSubdirectory
            ),
            let contents = try? String(contentsOf: url, encoding: .utf8)
        else {
            return "Could not load \(resource).txt from the app bundle."
        }
        return contents
    }
}
