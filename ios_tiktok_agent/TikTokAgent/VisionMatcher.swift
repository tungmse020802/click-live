import CoreGraphics
import UIKit
import Vision

struct MatchResult {
    let found: Bool
    let distance: Float

    var confidence: Float {
        max(0, min(1, 1 - distance))
    }
}

enum VisionMatcherError: LocalizedError {
    case missingTemplate
    case invalidImage
    case missingFeaturePrint

    var errorDescription: String? {
        switch self {
        case .missingTemplate:
            return "Khong tim thay template treasure_box_no_timer."
        case .invalidImage:
            return "Khong doc duoc anh."
        case .missingFeaturePrint:
            return "Vision khong tao duoc feature print."
        }
    }
}

final class VisionMatcher: @unchecked Sendable {
    static let ignoredBottomRatio: CGFloat = 0.35
    static let matchDistanceThreshold: Float = 0.42

    private let loadedKeywords = [
        "like", "comment", "share", "follow", "following", "for you"
    ]

    func checkLoaded(image: UIImage) async throws -> Bool {
        guard let cgImage = image.normalizedCGImage else {
            throw VisionMatcherError.invalidImage
        }

        return try await withCheckedThrowingContinuation { continuation in
            let request = VNRecognizeTextRequest { [loadedKeywords] request, error in
                if let error {
                    continuation.resume(throwing: error)
                    return
                }

                let texts = (request.results as? [VNRecognizedTextObservation])?
                    .compactMap { $0.topCandidates(1).first?.string.lowercased() } ?? []
                let loaded = texts.contains { text in
                    loadedKeywords.contains { text.contains($0) }
                }
                continuation.resume(returning: loaded)
            }
            request.recognitionLevel = .fast

            do {
                try VNImageRequestHandler(cgImage: cgImage).perform([request])
            } catch {
                continuation.resume(throwing: error)
            }
        }
    }

    func matchTreasureBox(in image: UIImage) async throws -> MatchResult {
        guard let template = UIImage(named: "treasure_box_no_timer") else {
            throw VisionMatcherError.missingTemplate
        }

        let reference = try featurePrint(for: template.removingTimerArea())
        let candidate = try featurePrint(for: image.removingTimerArea())

        var distance: Float = 1
        try candidate.computeDistance(&distance, to: reference)
        return MatchResult(
            found: distance <= Self.matchDistanceThreshold,
            distance: distance
        )
    }

    private func featurePrint(for image: UIImage) throws -> VNFeaturePrintObservation {
        guard let cgImage = image.normalizedCGImage else {
            throw VisionMatcherError.invalidImage
        }

        let request = VNGenerateImageFeaturePrintRequest()
        try VNImageRequestHandler(cgImage: cgImage).perform([request])
        guard let result = request.results?.first as? VNFeaturePrintObservation else {
            throw VisionMatcherError.missingFeaturePrint
        }
        return result
    }
}

private extension UIImage {
    var normalizedCGImage: CGImage? {
        if imageOrientation == .up, let cgImage {
            return cgImage
        }

        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        return UIGraphicsImageRenderer(size: size, format: format)
            .image { _ in draw(in: CGRect(origin: .zero, size: size)) }
            .cgImage
    }

    func removingTimerArea() -> UIImage {
        guard let source = normalizedCGImage else { return self }
        let keepHeight = max(
            1,
            Int(CGFloat(source.height) * (1 - VisionMatcher.ignoredBottomRatio))
        )
        let rect = CGRect(x: 0, y: 0, width: source.width, height: keepHeight)
        guard let cropped = source.cropping(to: rect) else { return self }
        return UIImage(cgImage: cropped)
    }
}
