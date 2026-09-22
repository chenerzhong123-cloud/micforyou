// swift-tools-version: 6.0

import PackageDescription

let package = Package(
    name: "MicForYouMenuBar",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "MicForYouMenuBar", targets: ["MicForYouMenuBar"]),
    ],
    targets: [
        .executableTarget(name: "MicForYouMenuBar"),
    ]
)
