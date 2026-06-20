import PhotosUI
import SwiftUI

@MainActor
final class AgentViewModel: ObservableObject {
    @Published var state: AgentState = .ready
    @Published var link = "https://www.tiktok.com/"
    @Published var selectedImage: UIImage?
    @Published var detail = "Timer se bi loai khoi vung nhan dang."
    @Published var confidence: Float?
    @Published var serverURL = "http://103.38.237.7:8787"
    @Published var lastJobID = 0
    @Published var isPolling = false
    @Published var uploadedScreenshotURL: String?

    private let matcher = VisionMatcher()
    private let queueClient = QueueClient()
    private var pollTask: Task<Void, Never>?
    private var selectedImageData: Data?

    func openTikTok() {
        guard let url = URL(string: link.trimmingCharacters(in: .whitespacesAndNewlines)) else {
            state = .failed
            detail = "Link khong hop le."
            return
        }

        state = .openingTikTok
        UIApplication.shared.open(url) { [weak self] opened in
            Task { @MainActor in
                self?.state = opened ? .waitingForScreenshot : .failed
                self?.detail = opened
                    ? "Chup man hinh TikTok, quay lai app va chon anh."
                    : "Khong mo duoc link TikTok."
            }
        }
    }

    func fetchAndOpenNextJob() async {
        do {
            detail = "Dang lay deeplink tu queue..."
            guard let job = try await queueClient.nextJob(
                serverURL: serverURL,
                afterID: lastJobID
            ) else {
                detail = "Chua co job moi."
                return
            }

            lastJobID = job.id
            link = job.url
            detail = "Queue #\(job.id): dang mo deeplink."
            openTikTok()
            try? await queueClient.report(
                serverURL: serverURL,
                jobID: job.id,
                status: "opened"
            )
        } catch {
            state = .failed
            detail = error.localizedDescription
        }
    }

    func setPolling(_ enabled: Bool) {
        pollTask?.cancel()
        pollTask = nil
        isPolling = enabled
        guard enabled else { return }

        pollTask = Task { [weak self] in
            while !Task.isCancelled {
                await self?.fetchAndOpenNextJob()
                try? await Task.sleep(for: .seconds(3))
            }
        }
    }

    func load(item: PhotosPickerItem?) async {
        guard let item else { return }
        do {
            guard let data = try await item.loadTransferable(type: Data.self),
                  let image = UIImage(data: data) else {
                throw VisionMatcherError.invalidImage
            }
            selectedImage = image
            selectedImageData = image.jpegData(compressionQuality: 0.9)
            confidence = nil
            uploadedScreenshotURL = nil
            state = .waitingForScreenshot
            detail = "Da nap screenshot. Dang upload len server..."
            await uploadSelectedScreenshot()
        } catch {
            state = .failed
            detail = error.localizedDescription
        }
    }

    func uploadSelectedScreenshot() async {
        guard let imageData = selectedImageData else {
            state = .failed
            detail = "Hay chon screenshot truoc."
            return
        }

        do {
            detail = "Dang upload screenshot cho queue #\(lastJobID)..."
            let result = try await queueClient.uploadScreenshot(
                serverURL: serverURL,
                jobID: lastJobID,
                imageData: imageData
            )
            uploadedScreenshotURL = result.url
            detail = "Da luu screenshot tren server: \(result.filename)"
            try? await queueClient.report(
                serverURL: serverURL,
                jobID: lastJobID,
                status: "screenshot_uploaded"
            )
        } catch {
            state = .failed
            detail = "Upload that bai: \(error.localizedDescription)"
        }
    }

    func analyze() async {
        guard let image = selectedImage else {
            state = .failed
            detail = "Hay chon screenshot truoc."
            return
        }

        do {
            state = .checkingLoad
            let loaded = try await matcher.checkLoaded(image: image)
            state = loaded ? .loaded : .loadTimeout
            detail = loaded
                ? "OCR thay dau hieu giao dien TikTok da load."
                : "Khong thay keyword load; van tiep tuc tim object."

            state = .detectingObject
            let result = try await matcher.matchTreasureBox(in: image)
            confidence = result.confidence
            state = result.found ? .objectFound : .objectNotFound
            detail = result.found
                ? "Da tim thay object. Vung 35% phia duoi da bi bo qua."
                : "Chua match template. Distance: \(String(format: "%.3f", result.distance))."
        } catch {
            state = .failed
            detail = error.localizedDescription
        }
    }
}
