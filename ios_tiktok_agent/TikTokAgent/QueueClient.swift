import Foundation

struct QueueJob: Decodable, Sendable {
    let id: Int
    let url: String
}

private struct NextJobResponse: Decodable {
    let job: QueueJob?
}

private struct JobResult: Encodable {
    let job_id: Int
    let status: String
    let device_id: String
    let error: String
}

struct ScreenshotUploadResponse: Decodable, Sendable {
    let filename: String
    let url: String
}

enum QueueClientError: LocalizedError {
    case invalidServerURL
    case invalidResponse(Int)

    var errorDescription: String? {
        switch self {
        case .invalidServerURL:
            return "Queue server URL khong hop le."
        case .invalidResponse(let status):
            return "Queue server tra ve HTTP \(status)."
        }
    }
}

final class QueueClient: Sendable {
    func nextJob(serverURL: String, afterID: Int) async throws -> QueueJob? {
        guard var components = URLComponents(
            string: normalize(serverURL) + "/api/phone/next-job"
        ) else {
            throw QueueClientError.invalidServerURL
        }
        components.queryItems = [
            URLQueryItem(name: "wait", value: "0"),
            URLQueryItem(name: "after_id", value: String(afterID)),
            URLQueryItem(name: "device_id", value: "iphone"),
        ]
        guard let url = components.url else {
            throw QueueClientError.invalidServerURL
        }

        let (data, response) = try await URLSession.shared.data(from: url)
        try validate(response)
        return try JSONDecoder().decode(NextJobResponse.self, from: data).job
    }

    func report(
        serverURL: String,
        jobID: Int,
        status: String,
        error: String = ""
    ) async throws {
        guard let url = URL(
            string: normalize(serverURL) + "/api/phone/job-result"
        ) else {
            throw QueueClientError.invalidServerURL
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(
            JobResult(
                job_id: jobID,
                status: status,
                device_id: "iphone",
                error: error
            )
        )
        let (_, response) = try await URLSession.shared.data(for: request)
        try validate(response)
    }

    func uploadScreenshot(
        serverURL: String,
        jobID: Int,
        imageData: Data
    ) async throws -> ScreenshotUploadResponse {
        guard let url = URL(
            string: normalize(serverURL) + "/api/phone/screenshot"
        ) else {
            throw QueueClientError.invalidServerURL
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("image/jpeg", forHTTPHeaderField: "Content-Type")
        request.setValue(String(jobID), forHTTPHeaderField: "X-Job-ID")
        request.setValue("iphone", forHTTPHeaderField: "X-Device-ID")
        request.httpBody = imageData

        let (data, response) = try await URLSession.shared.data(for: request)
        try validate(response)
        return try JSONDecoder().decode(ScreenshotUploadResponse.self, from: data)
    }

    private func validate(_ response: URLResponse) throws {
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else {
            throw QueueClientError.invalidResponse(status)
        }
    }

    private func normalize(_ value: String) -> String {
        value.trimmingCharacters(in: .whitespacesAndNewlines)
            .replacingOccurrences(of: #"/+$"#, with: "", options: .regularExpression)
    }
}
