import PhotosUI
import SwiftUI

struct ContentView: View {
    @StateObject private var model = AgentViewModel()
    @State private var photoItem: PhotosPickerItem?

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 16) {
                    statusCard

                    TextField("Queue server", text: $model.serverURL)
                        .textInputAutocapitalization(.never)
                        .keyboardType(.URL)
                        .textFieldStyle(.roundedBorder)

                    Button("Lay deeplink moi tu queue") {
                        Task { await model.fetchAndOpenNextJob() }
                    }
                    .buttonStyle(.borderedProminent)

                    Toggle(
                        "Tu dong kiem tra queue moi moi 3 giay",
                        isOn: Binding(
                            get: { model.isPolling },
                            set: { model.setPolling($0) }
                        )
                    )

                    TextField("TikTok URL", text: $model.link)
                        .textInputAutocapitalization(.never)
                        .keyboardType(.URL)
                        .textFieldStyle(.roundedBorder)

                    Button("Mo TikTok") {
                        model.openTikTok()
                    }
                    .buttonStyle(.borderedProminent)
                    .frame(maxWidth: .infinity)

                    PhotosPicker(
                        selection: $photoItem,
                        matching: .images
                    ) {
                        Label("Chon screenshot", systemImage: "photo")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.bordered)
                    .onChange(of: photoItem) { _, value in
                        Task { await model.load(item: value) }
                    }

                    if let image = model.selectedImage {
                        Image(uiImage: image)
                            .resizable()
                            .scaledToFit()
                            .frame(maxHeight: 420)
                            .clipShape(RoundedRectangle(cornerRadius: 12))
                    }

                    Button("Upload screenshot len server") {
                        Task { await model.uploadSelectedScreenshot() }
                    }
                    .buttonStyle(.bordered)
                    .disabled(model.selectedImage == nil)

                    if let path = model.uploadedScreenshotURL {
                        Text("Server: \(model.serverURL)\(path)")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .textSelection(.enabled)
                    }

                    Button("Kiem tra load va tim hop qua") {
                        Task { await model.analyze() }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(model.selectedImage == nil)

                    Text("Matcher bo qua 35% phia duoi anh, nen timer nhu 00:38 khong duoc dung de nhan dang.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
                .padding()
            }
            .navigationTitle("TikTok Agent")
        }
    }

    private var statusCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(model.state.rawValue)
                .font(.headline)
            Text(model.detail)
                .font(.subheadline)
                .foregroundStyle(.secondary)
            if let confidence = model.confidence {
                ProgressView(value: Double(confidence))
                Text("Confidence: \(Int(confidence * 100))%")
                    .font(.caption)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding()
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 12))
    }
}
